import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getEmployeeDashboard } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Clock, Calendar, FileText, Bell, ArrowRight } from 'lucide-react';
import { format, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';

const leaveTypeLabels = {
  ferias: 'Férias',
  falta: 'Falta',
  doenca: 'Doença',
  folga: 'Folga'
};

const statusLabels = {
  pendente: 'Pendente',
  aprovado: 'Aprovado',
  recusado: 'Recusado'
};

export default function EmployeeDashboard() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboard();
  }, []);

  const fetchDashboard = async () => {
    try {
      const response = await getEmployeeDashboard();
      setData(response.data);
    } catch (error) {
      console.error('Error fetching dashboard:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in pb-4" data-testid="employee-dashboard">
      {/* Welcome Header */}
      <div className="bg-primary text-primary-foreground rounded-xl p-6">
        <h1 className="text-xl font-heading font-bold">Olá, {user?.name}!</h1>
        <p className="text-primary-foreground/80 text-sm mt-1">
          {format(new Date(), "EEEE, d 'de' MMMM", { locale: pt })}
        </p>
        {data?.employee && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge variant="secondary" className="bg-white/20 text-white hover:bg-white/30">
              {data.employee.company_name}
            </Badge>
            <Badge variant="secondary" className="bg-white/20 text-white hover:bg-white/30">
              {data.employee.location_name}
            </Badge>
          </div>
        )}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-2 gap-3">
        <Link to="/colaborador/ponto" data-testid="quick-action-ponto">
          <Card className="card-hover h-full">
            <CardContent className="p-4 flex flex-col items-center justify-center text-center">
              <div className="p-3 bg-green-100 rounded-full mb-2">
                <Clock className="h-6 w-6 text-green-600" />
              </div>
              <p className="font-medium text-sm">Registar Ponto</p>
            </CardContent>
          </Card>
        </Link>
        <Link to="/colaborador/ausencias" data-testid="quick-action-ausencias">
          <Card className="card-hover h-full">
            <CardContent className="p-4 flex flex-col items-center justify-center text-center">
              <div className="p-3 bg-blue-100 rounded-full mb-2">
                <Calendar className="h-6 w-6 text-blue-600" />
              </div>
              <p className="font-medium text-sm">Pedir Ausência</p>
            </CardContent>
          </Card>
        </Link>
      </div>

      {/* Pending Requests */}
      {data?.pending_requests?.length > 0 && (
        <Card data-testid="pending-requests-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Bell className="h-4 w-4" />
              Pedidos Pendentes
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.pending_requests.map((request) => (
              <div key={request.id} className="flex items-center justify-between p-3 bg-muted rounded-lg">
                <div>
                  <p className="font-medium text-sm">{leaveTypeLabels[request.leave_type]}</p>
                  <p className="text-xs text-muted-foreground">
                    {format(parseISO(request.start_date), 'dd/MM')} - {format(parseISO(request.end_date), 'dd/MM')}
                  </p>
                </div>
                <Badge className="badge-pendente">{statusLabels.pendente}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Upcoming Leave */}
      {data?.upcoming_leave?.length > 0 && (
        <Card data-testid="upcoming-leave-card">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Calendar className="h-4 w-4" />
                Próximas Ausências
              </CardTitle>
              <Link to="/colaborador/ausencias">
                <Button variant="ghost" size="sm">
                  Ver todas
                  <ArrowRight className="h-4 w-4 ml-1" />
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.upcoming_leave.slice(0, 3).map((leave) => (
              <div key={leave.id} className="flex items-center justify-between p-3 bg-muted rounded-lg">
                <div>
                  <p className="font-medium text-sm">{leaveTypeLabels[leave.leave_type]}</p>
                  <p className="text-xs text-muted-foreground">
                    {format(parseISO(leave.start_date), 'dd/MM/yyyy')} - {format(parseISO(leave.end_date), 'dd/MM/yyyy')}
                  </p>
                </div>
                <Badge className="badge-aprovado">{statusLabels.aprovado}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Recent Time Records */}
      <Card data-testid="recent-records-card">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Clock className="h-4 w-4" />
              Últimos Registos de Ponto
            </CardTitle>
            <Link to="/colaborador/ponto">
              <Button variant="ghost" size="sm">
                Ver histórico
                <ArrowRight className="h-4 w-4 ml-1" />
              </Button>
            </Link>
          </div>
        </CardHeader>
        <CardContent>
          {data?.recent_records?.length > 0 ? (
            <div className="space-y-2">
              {data.recent_records.slice(0, 5).map((record) => (
                <div key={record.id} className="flex items-center justify-between p-3 bg-muted rounded-lg">
                  <div className="flex items-center gap-3">
                    <Badge variant={record.record_type === 'entrada' ? 'default' : 'secondary'}>
                      {record.record_type === 'entrada' ? 'Entrada' : 'Saída'}
                    </Badge>
                    <span className="text-sm">
                      {format(parseISO(record.time), "dd/MM 'às' HH:mm", { locale: pt })}
                    </span>
                  </div>
                  {record.corrected && (
                    <Badge variant="outline" className="text-yellow-600 border-yellow-300 text-xs">
                      Corrigido
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-4">
              Sem registos de ponto recentes
            </p>
          )}
        </CardContent>
      </Card>

      {/* Employee Info */}
      {data?.employee && (
        <Card data-testid="employee-info-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Informações</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Vacation Days Summary */}
            <div className="p-4 bg-blue-50 rounded-lg border border-blue-100">
              <p className="text-sm font-medium text-blue-900 mb-2">Férias {new Date().getFullYear()}</p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-2xl font-bold text-blue-600">{data.employee.vacation_days}</p>
                  <p className="text-xs text-blue-700">Total</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-orange-600">{data.employee.vacation_days_used || 0}</p>
                  <p className="text-xs text-orange-700">Utilizados</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-green-600">{data.employee.vacation_days_available ?? data.employee.vacation_days}</p>
                  <p className="text-xs text-green-700">Disponíveis</p>
                </div>
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-muted-foreground">Cargo</p>
                <p className="text-sm font-medium">{data.employee.position}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Data de Entrada</p>
                <p className="text-sm font-medium">{format(parseISO(data.employee.start_date), 'dd/MM/yyyy')}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Contrato</p>
                <p className="text-sm font-medium capitalize">{data.employee.contract_type.replace('_', ' ')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
