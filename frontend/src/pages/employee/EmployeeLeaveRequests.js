import React, { useState, useEffect } from 'react';
import { getLeaveRequests, createLeaveRequest } from '../../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Textarea } from '../../components/ui/textarea';
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { Calendar, Plus, Clock, Check, X } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO, differenceInDays } from 'date-fns';

const leaveTypes = [
  { value: 'ferias', label: 'Férias' },
  { value: 'falta', label: 'Falta' },
  { value: 'doenca', label: 'Doença' },
  { value: 'folga', label: 'Folga' },
];

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

export default function EmployeeLeaveRequests() {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [formData, setFormData] = useState({
    leave_type: '',
    start_date: '',
    end_date: '',
    observation: ''
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchRequests();
  }, []);

  const fetchRequests = async () => {
    setLoading(true);
    try {
      const response = await getLeaveRequests();
      setRequests(response.data);
    } catch (error) {
      toast.error('Erro ao carregar pedidos');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.leave_type || !formData.start_date || !formData.end_date) {
      toast.error('Preencha todos os campos obrigatórios');
      return;
    }
    if (formData.start_date > formData.end_date) {
      toast.error('Data de início não pode ser posterior à data de fim');
      return;
    }
    setSaving(true);
    try {
      await createLeaveRequest(formData);
      toast.success('Pedido criado com sucesso!');
      setDialogOpen(false);
      setFormData({ leave_type: '', start_date: '', end_date: '', observation: '' });
      fetchRequests();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao criar pedido');
    } finally {
      setSaving(false);
    }
  };

  const getDuration = (request) => {
    const days = request?.counted_days ?? (differenceInDays(parseISO(request.end_date), parseISO(request.start_date)) + 1);
    return `${days} dia${days > 1 ? 's' : ''}`;
  };

  const isManagerCreated = (request) => request?.created_by && request.created_by !== 'colaborador';

  const pendingRequests = requests.filter(r => r.status === 'pendente');
  const approvedRequests = requests.filter(r => r.status === 'aprovado');
  const rejectedRequests = requests.filter(r => r.status === 'recusado');

  const RequestCard = ({ request }) => (
    <div className="p-4 bg-muted rounded-lg space-y-2" data-testid={`request-${request.id}`}>
      	<div className="flex items-center justify-between">
        <div className="flex flex-wrap items-center gap-2" data-testid={`request-badges-${request.id}`}>
          <Badge variant="outline" data-testid={`request-type-${request.id}`}>{leaveTypeLabels[request.leave_type]}</Badge>
          {isManagerCreated(request) && (
            <Badge variant="secondary" data-testid={`request-created-by-${request.id}`}>
              Criado pelo gestor
            </Badge>
          )}
        </div>
        <Badge className={`badge-${request.status}`} data-testid={`request-status-${request.id}`}>
          {statusLabels[request.status]}
        </Badge>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <Calendar className="h-4 w-4 text-muted-foreground" />
        <span>
          {format(parseISO(request.start_date), 'dd/MM/yyyy')} - {format(parseISO(request.end_date), 'dd/MM/yyyy')}
        </span>
      </div>
      <div className="flex flex-col gap-1 text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4" />
          <span>{getDuration(request)}</span>
        </div>
        {request?.counted_days !== undefined && (
          <span data-testid={`request-counted-days-${request.id}`}>
            Dias contabilizados: {request.counted_days}
          </span>
        )}
      </div>
      {request.observation && (
        <p className="text-sm text-muted-foreground border-t pt-2 mt-2">
          {request.observation}
        </p>
      )}
      {request.admin_response && (
        <p className="text-sm bg-white p-2 rounded border mt-2">
          <span className="font-medium">Resposta: </span>
          {request.admin_response}
        </p>
      )}
    </div>
  );

  return (
    <div className="space-y-6 animate-fade-in pb-4" data-testid="employee-leave-requests-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-heading font-bold">Ausências</h1>
          <p className="text-sm text-muted-foreground">Férias, faltas e folgas</p>
        </div>
        <Button onClick={() => setDialogOpen(true)} data-testid="new-request-btn">
          <Plus className="h-4 w-4 mr-2" />
          Novo Pedido
        </Button>
      </div>

      <Tabs defaultValue="pendente" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="pendente" className="relative" data-testid="tab-pendente">
            Pendentes
            {pendingRequests.length > 0 && (
              <Badge className="ml-2 h-5 w-5 p-0 flex items-center justify-center">
                {pendingRequests.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="aprovado" data-testid="tab-aprovado">Aprovados</TabsTrigger>
          <TabsTrigger value="recusado" data-testid="tab-recusado">Recusados</TabsTrigger>
        </TabsList>
        
        <TabsContent value="pendente" className="mt-4">
          {loading ? (
            <div className="flex items-center justify-center h-20">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : pendingRequests.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-8 text-center">
                <Clock className="h-10 w-10 text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">Sem pedidos pendentes</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {pendingRequests.map(request => (
                <RequestCard key={request.id} request={request} />
              ))}
            </div>
          )}
        </TabsContent>
        
        <TabsContent value="aprovado" className="mt-4">
          {loading ? (
            <div className="flex items-center justify-center h-20">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : approvedRequests.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-8 text-center">
                <Check className="h-10 w-10 text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">Sem pedidos aprovados</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {approvedRequests.map(request => (
                <RequestCard key={request.id} request={request} />
              ))}
            </div>
          )}
        </TabsContent>
        
        <TabsContent value="recusado" className="mt-4">
          {loading ? (
            <div className="flex items-center justify-center h-20">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : rejectedRequests.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-8 text-center">
                <X className="h-10 w-10 text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">Sem pedidos recusados</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {rejectedRequests.map(request => (
                <RequestCard key={request.id} request={request} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* New Request Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="new-request-dialog">
          <DialogHeader>
            <DialogTitle>Novo Pedido de Ausência</DialogTitle>
            <DialogDescription>
              Preencha os dados para solicitar uma ausência
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="leave_type">Tipo de Ausência *</Label>
                <Select
                  value={formData.leave_type}
                  onValueChange={(value) => setFormData({ ...formData, leave_type: value })}
                >
                  <SelectTrigger data-testid="leave-type-select">
                    <SelectValue placeholder="Selecionar tipo" />
                  </SelectTrigger>
                  <SelectContent>
                    {leaveTypes.map((type) => (
                      <SelectItem key={type.value} value={type.value}>
                        {type.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="start_date">Data Início *</Label>
                  <Input
                    id="start_date"
                    type="date"
                    value={formData.start_date}
                    onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                    required
                    data-testid="start-date-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="end_date">Data Fim *</Label>
                  <Input
                    id="end_date"
                    type="date"
                    value={formData.end_date}
                    onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                    required
                    data-testid="end-date-input"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="observation">Observação</Label>
                <Textarea
                  id="observation"
                  value={formData.observation}
                  onChange={(e) => setFormData({ ...formData, observation: e.target.value })}
                  placeholder="Adicione uma nota (opcional)"
                  rows={3}
                  data-testid="observation-input"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving} data-testid="submit-request-btn">
                {saving ? 'A enviar...' : 'Enviar Pedido'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
