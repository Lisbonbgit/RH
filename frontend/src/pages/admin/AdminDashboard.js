import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { getAdminDashboard, getCalendarLeaves, respondLeaveRequest } from '../../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Calendar } from '../../components/ui/calendar';
import { Users, Clock, CalendarDays, Palmtree, Cake, Check, X, PartyPopper, Briefcase, Coffee, UserMinus, Plane } from 'lucide-react';
import { format, parseISO, isSameDay, isWithinInterval } from 'date-fns';
import { pt } from 'date-fns/locale';
import { toast } from 'sonner';

const leaveTypeLabels = { ferias: 'Férias', falta: 'Falta', doenca: 'Doença', folga: 'Folga', ausencia: 'Ausência' };
const statusLabels = { pendente: 'Pendente', aprovado: 'Aprovado', recusado: 'Recusado' };

const avatarColors = ['bg-blue-500', 'bg-teal-500', 'bg-indigo-500', 'bg-amber-500', 'bg-rose-500', 'bg-emerald-500', 'bg-violet-500', 'bg-cyan-600'];
const colorFromName = (name) => {
  let h = 0;
  for (const ch of name || '?') h += ch.charCodeAt(0);
  return avatarColors[h % avatarColors.length];
};
const initials = (name) =>
  (name || '?').split(' ').filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase();

const Avatar = ({ person, size = 'h-10 w-10' }) =>
  person?.photo ? (
    <img src={person.photo} alt={person.name} className={`${size} rounded-full object-cover ring-2 ring-card`} title={person.name} />
  ) : (
    <div className={`${size} rounded-full ${colorFromName(person?.name)} text-white flex items-center justify-center text-xs font-semibold ring-2 ring-card`} title={person?.name}>
      {initials(person?.name)}
    </div>
  );

const AvatarGroup = ({ people = [], icon: Icon, label, accent }) => (
  <div>
    <div className="flex items-center gap-2 mb-2">
      <Icon className={`h-4 w-4 ${accent}`} />
      <span className="text-sm font-medium">{label}</span>
      <span className="text-xs text-muted-foreground">({people.length})</span>
    </div>
    {people.length === 0 ? (
      <p className="text-xs text-muted-foreground pl-6">Ninguém</p>
    ) : (
      <div className="flex flex-wrap items-center gap-1 pl-6">
        {people.slice(0, 12).map((p) => (
          <Avatar key={p.id} person={p} size="h-9 w-9" />
        ))}
        {people.length > 12 && (
          <div className="h-9 w-9 rounded-full bg-muted text-muted-foreground flex items-center justify-center text-xs font-semibold">
            +{people.length - 12}
          </div>
        )}
      </div>
    )}
  </div>
);

const greeting = () => {
  const h = new Date().getHours();
  if (h < 12) return 'Bom dia';
  if (h < 19) return 'Boa tarde';
  return 'Boa noite';
};

export default function AdminDashboard() {
  const { selectedCompany } = useOutletContext();
  const { user } = useAuth();
  const [stats, setStats] = useState(null);
  const [leaves, setLeaves] = useState([]);
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompany]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [dashboardRes, leavesRes] = await Promise.all([
        getAdminDashboard(selectedCompany?.id),
        getCalendarLeaves({ company_id: selectedCompany?.id, month: new Date().getMonth() + 1, year: new Date().getFullYear() }),
      ]);
      setStats(dashboardRes.data);
      setLeaves(leavesRes.data);
    } catch (error) {
      console.error('Error fetching dashboard:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleRespond = async (id, status) => {
    try {
      await respondLeaveRequest(id, status, '');
      toast.success(`Pedido ${status === 'aprovado' ? 'aprovado' : 'recusado'}`);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao responder');
    }
  };

  const getDayLeaves = (day) =>
    leaves.filter((leave) => {
      const start = parseISO(leave.start_date);
      const end = parseISO(leave.end_date);
      return isWithinInterval(day, { start, end }) || isSameDay(day, start) || isSameDay(day, end);
    });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  const pending = (stats?.recent_requests || []).filter((r) => r.status === 'pendente');
  const metrics = [
    { label: 'Colaboradores', value: stats?.total_employees || 0, icon: Users, color: 'text-blue-600', bg: 'bg-blue-50' },
    { label: 'A trabalhar agora', value: stats?.working_now || 0, icon: Clock, color: 'text-teal-600', bg: 'bg-teal-50' },
    { label: 'De férias/ausentes hoje', value: stats?.on_leave_today || 0, icon: Palmtree, color: 'text-amber-600', bg: 'bg-amber-50' },
    { label: 'Pedidos pendentes', value: stats?.pending_requests || 0, icon: CalendarDays, color: 'text-rose-600', bg: 'bg-rose-50' },
  ];

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-dashboard">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-2xl brand-gradient text-white p-6 md:p-8">
        <div className="absolute inset-0 opacity-50" style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.12) 1px, transparent 0)', backgroundSize: '22px 22px' }} />
        <div className="absolute -top-16 -right-10 h-48 w-48 rounded-full bg-white/10 blur-2xl" />
        <div className="relative">
          <p className="text-sm text-white/80 capitalize">{format(new Date(), "EEEE, d 'de' MMMM", { locale: pt })}</p>
          <h1 className="text-2xl md:text-3xl font-heading font-bold mt-1">
            {greeting()}, {user?.name?.split(' ')[0] || 'bem-vindo'} 👋
          </h1>
          <p className="text-white/80 mt-1 text-sm">
            {selectedCompany ? `A ver: ${selectedCompany.name}` : 'Visão geral de todas as empresas'}
          </p>
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {metrics.map((m) => (
          <Card key={m.label} className="card-hover" data-testid={`stat-${m.label}`}>
            <CardContent className="p-4 md:p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs md:text-sm text-muted-foreground font-medium">{m.label}</span>
                <span className={`p-1.5 rounded-lg ${m.bg}`}><m.icon className={`h-4 w-4 ${m.color}`} /></span>
              </div>
              <p className="text-3xl font-heading font-bold mt-2">{m.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Esquerda (2 col) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Quem está hoje */}
          <Card data-testid="whos-in-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><Briefcase className="h-4 w-4" /> Quem está hoje</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <AvatarGroup people={stats?.whos_in?.working || []} icon={Clock} label="A trabalhar" accent="text-teal-600" />
              <AvatarGroup people={stats?.whos_in?.vacation || []} icon={Palmtree} label="Férias" accent="text-amber-600" />
              <AvatarGroup people={stats?.whos_in?.dayoff || []} icon={Coffee} label="Folga" accent="text-violet-600" />
              <AvatarGroup people={stats?.whos_in?.absent || []} icon={UserMinus} label="Ausentes" accent="text-rose-600" />
            </CardContent>
          </Card>

          {/* Calendário */}
          <Card data-testid="calendar-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><CalendarDays className="h-4 w-4" /> Calendário de Ausências</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col md:flex-row gap-6">
                <Calendar
                  mode="single"
                  selected={selectedDate}
                  onSelect={setSelectedDate}
                  locale={pt}
                  className="rounded-md border"
                  modifiers={{ hasLeave: (date) => getDayLeaves(date).length > 0 }}
                  modifiersStyles={{ hasLeave: { backgroundColor: 'hsl(var(--primary) / 0.12)', fontWeight: 'bold' } }}
                />
                <div className="flex-1 space-y-3">
                  <h4 className="font-medium">{selectedDate ? format(selectedDate, "d 'de' MMMM", { locale: pt }) : 'Selecione uma data'}</h4>
                  {selectedDate && getDayLeaves(selectedDate).length > 0 ? (
                    <div className="space-y-2">
                      {getDayLeaves(selectedDate).map((leave) => (
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
        </div>

        {/* Direita (1 col) */}
        <div className="space-y-6">
          {/* Pedidos pendentes */}
          <Card data-testid="pending-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><CalendarDays className="h-4 w-4" /> Pedidos pendentes</CardTitle>
            </CardHeader>
            <CardContent>
              {pending.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">Sem pedidos a aguardar</p>
              ) : (
                <div className="space-y-3">
                  {pending.map((r) => (
                    <div key={r.id} className="flex items-center justify-between gap-2 p-3 bg-muted rounded-lg">
                      <div className="flex items-center gap-2 min-w-0">
                        <Avatar person={r} size="h-8 w-8" />
                        <div className="min-w-0">
                          <p className="font-medium text-sm truncate">{r.employee_name}</p>
                          <p className="text-xs text-muted-foreground">{leaveTypeLabels[r.leave_type] || r.leave_type}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button size="icon" variant="ghost" className="h-8 w-8 text-green-600 hover:bg-green-50" onClick={() => handleRespond(r.id, 'aprovado')} data-testid={`dash-approve-${r.id}`}>
                          <Check className="h-4 w-4" />
                        </Button>
                        <Button size="icon" variant="ghost" className="h-8 w-8 text-red-600 hover:bg-red-50" onClick={() => handleRespond(r.id, 'recusado')} data-testid={`dash-reject-${r.id}`}>
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Próximos aniversários */}
          <Card data-testid="birthdays-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><PartyPopper className="h-4 w-4" /> Próximos aniversários</CardTitle>
            </CardHeader>
            <CardContent>
              {(stats?.upcoming_birthdays || []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">Nenhum nos próximos 30 dias</p>
              ) : (
                <div className="space-y-3">
                  {stats.upcoming_birthdays.map((b, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <Avatar person={b} size="h-9 w-9" />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{b.name}</p>
                        <p className="text-xs text-muted-foreground flex items-center gap-1">
                          <Cake className="h-3 w-3" /> {format(parseISO(b.date), "d 'de' MMM", { locale: pt })}
                        </p>
                      </div>
                      <Badge variant="outline" className="text-xs">
                        {b.days_until === 0 ? 'Hoje! 🎉' : b.days_until === 1 ? 'Amanhã' : `${b.days_until} dias`}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Próximas férias */}
          <Card data-testid="upcoming-leaves-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base"><Plane className="h-4 w-4" /> Próximas férias</CardTitle>
            </CardHeader>
            <CardContent>
              {(stats?.upcoming_leaves || []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">Sem férias agendadas</p>
              ) : (
                <div className="space-y-3">
                  {stats.upcoming_leaves.map((lv, i) => (
                    <div key={`${lv.employee_name}-${lv.start_date}`} className="flex items-center gap-3">
                      <Avatar person={{ name: lv.employee_name, photo: lv.photo }} size="h-9 w-9" />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{lv.employee_name}</p>
                        <p className="text-xs text-muted-foreground flex items-center gap-1">
                          <Palmtree className="h-3 w-3" /> {format(parseISO(lv.start_date), 'd MMM', { locale: pt })} - {format(parseISO(lv.end_date), 'd MMM', { locale: pt })}
                        </p>
                      </div>
                      <Badge variant="outline" className="text-xs shrink-0">
                        {lv.days_until === 0 ? 'Hoje' : lv.days_until === 1 ? 'Amanhã' : `daqui a ${lv.days_until} dias`}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Colaboradores por empresa */}
          {stats?.employees_by_company?.length > 0 && (
            <Card data-testid="employees-by-company-card">
              <CardHeader>
                <CardTitle className="text-base">Colaboradores por empresa</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {stats.employees_by_company.map((item, index) => (
                    <div key={index} className="flex items-center gap-3">
                      <div className="w-24 truncate text-sm">{item.company}</div>
                      <div className="flex-1 h-2.5 bg-muted rounded-full overflow-hidden">
                        <div className="h-full brand-gradient rounded-full" style={{ width: `${(item.count / Math.max(...stats.employees_by_company.map((e) => e.count), 1)) * 100}%` }} />
                      </div>
                      <div className="w-6 text-right font-bold text-sm">{item.count}</div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
