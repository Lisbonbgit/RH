import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getAdminDashboard, getCalendarLeaves } from '../../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Calendar } from '../../components/ui/calendar';
import { Users, Building2, Clock, CalendarDays, TrendingUp } from 'lucide-react';
import { format, parseISO, isSameDay, isWithinInterval } from 'date-fns';
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

export default function AdminDashboard() {
  const { selectedCompany } = useOutletContext();
  const [stats, setStats] = useState(null);
  const [leaves, setLeaves] = useState([]);
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
  }, [selectedCompany]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [dashboardRes, leavesRes] = await Promise.all([
        getAdminDashboard(selectedCompany?.id),
        getCalendarLeaves({ 
          company_id: selectedCompany?.id,
          month: new Date().getMonth() + 1,
          year: new Date().getFullYear()
        })
      ]);
      setStats(dashboardRes.data);
      setLeaves(leavesRes.data);
    } catch (error) {
      console.error('Error fetching dashboard:', error);
    } finally {
      setLoading(false);
    }
  };

  const getDayLeaves = (day) => {
    return leaves.filter(leave => {
      const start = parseISO(leave.start_date);
      const end = parseISO(leave.end_date);
      return isWithinInterval(day, { start, end }) || isSameDay(day, start) || isSameDay(day, end);
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-dashboard">
      <div>
        <h1 className="text-2xl md:text-3xl font-heading font-bold">Dashboard</h1>
        <p className="text-muted-foreground mt-1">
          {selectedCompany ? `Visão geral - ${selectedCompany.name}` : 'Visão geral de todas as empresas'}
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="card-hover" data-testid="stat-employees">
          <CardContent className="p-4 md:p-6">
            <div className="flex items-center gap-4">
              <div className="p-2 md:p-3 bg-blue-100 rounded-lg">
                <Users className="h-5 w-5 md:h-6 md:w-6 text-blue-600" />
              </div>
              <div>
                <p className="text-2xl md:text-3xl font-bold">{stats?.total_employees || 0}</p>
                <p className="text-xs md:text-sm text-muted-foreground">Colaboradores</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="card-hover" data-testid="stat-companies">
          <CardContent className="p-4 md:p-6">
            <div className="flex items-center gap-4">
              <div className="p-2 md:p-3 bg-purple-100 rounded-lg">
                <Building2 className="h-5 w-5 md:h-6 md:w-6 text-purple-600" />
              </div>
              <div>
                <p className="text-2xl md:text-3xl font-bold">{stats?.total_companies || 0}</p>
                <p className="text-xs md:text-sm text-muted-foreground">Empresas</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="card-hover" data-testid="stat-pending">
          <CardContent className="p-4 md:p-6">
            <div className="flex items-center gap-4">
              <div className="p-2 md:p-3 bg-yellow-100 rounded-lg">
                <CalendarDays className="h-5 w-5 md:h-6 md:w-6 text-yellow-600" />
              </div>
              <div>
                <p className="text-2xl md:text-3xl font-bold">{stats?.pending_requests || 0}</p>
                <p className="text-xs md:text-sm text-muted-foreground">Pedidos Pendentes</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="card-hover" data-testid="stat-today">
          <CardContent className="p-4 md:p-6">
            <div className="flex items-center gap-4">
              <div className="p-2 md:p-3 bg-green-100 rounded-lg">
                <Clock className="h-5 w-5 md:h-6 md:w-6 text-green-600" />
              </div>
              <div>
                <p className="text-2xl md:text-3xl font-bold">{stats?.today_records || 0}</p>
                <p className="text-xs md:text-sm text-muted-foreground">Registos Hoje</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Calendar */}
        <Card className="lg:col-span-2" data-testid="calendar-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5" />
              Calendário de Ausências
            </CardTitle>
            <CardDescription>
              Visualize férias e ausências aprovadas
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col md:flex-row gap-6">
              <Calendar
                mode="single"
                selected={selectedDate}
                onSelect={setSelectedDate}
                locale={pt}
                className="rounded-md border"
                modifiers={{
                  hasLeave: (date) => getDayLeaves(date).length > 0
                }}
                modifiersStyles={{
                  hasLeave: { backgroundColor: 'hsl(var(--primary) / 0.1)', fontWeight: 'bold' }
                }}
              />
              <div className="flex-1 space-y-3">
                <h4 className="font-medium">
                  {selectedDate ? format(selectedDate, "d 'de' MMMM, yyyy", { locale: pt }) : 'Selecione uma data'}
                </h4>
                {selectedDate && getDayLeaves(selectedDate).length > 0 ? (
                  <div className="space-y-2">
                    {getDayLeaves(selectedDate).map(leave => (
                      <div key={leave.id} className="p-3 bg-muted rounded-lg">
                        <p className="font-medium text-sm">{leave.employee_name}</p>
                        <p className="text-xs text-muted-foreground">
                          {leaveTypeLabels[leave.leave_type]} • {format(parseISO(leave.start_date), 'dd/MM')} - {format(parseISO(leave.end_date), 'dd/MM')}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">Sem ausências nesta data</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Recent Requests */}
        <Card data-testid="recent-requests-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Pedidos Recentes
            </CardTitle>
            <CardDescription>
              Últimos pedidos de ausência
            </CardDescription>
          </CardHeader>
          <CardContent>
            {stats?.recent_requests?.length > 0 ? (
              <div className="space-y-3">
                {stats.recent_requests.map(request => (
                  <div key={request.id} className="flex items-center justify-between p-3 bg-muted rounded-lg">
                    <div>
                      <p className="font-medium text-sm">{request.employee_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {leaveTypeLabels[request.leave_type]}
                      </p>
                    </div>
                    <Badge className={`badge-${request.status}`}>
                      {statusLabels[request.status]}
                    </Badge>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                Sem pedidos recentes
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Employees by Company Chart */}
      {stats?.employees_by_company?.length > 0 && (
        <Card data-testid="employees-by-company-card">
          <CardHeader>
            <CardTitle>Colaboradores por Empresa</CardTitle>
            <CardDescription>Distribuição de colaboradores</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {stats.employees_by_company.map((item, index) => (
                <div key={index} className="flex items-center gap-4">
                  <div className="w-32 md:w-48 truncate font-medium text-sm">{item.company}</div>
                  <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-primary rounded-full transition-all"
                      style={{ 
                        width: `${(item.count / Math.max(...stats.employees_by_company.map(e => e.count))) * 100}%` 
                      }}
                    />
                  </div>
                  <div className="w-8 text-right font-bold text-sm">{item.count}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
