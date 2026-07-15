import React, { useState, useEffect, useMemo } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getCalendarLeaves, getEmployees, getVacationBalance } from '../../lib/api';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { CalendarRange, ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { toast } from 'sonner';
import {
  format,
  parseISO,
  startOfMonth,
  endOfMonth,
  eachDayOfInterval,
  isWeekend,
  addMonths,
  subMonths,
  differenceInCalendarDays,
} from 'date-fns';
import { pt } from 'date-fns/locale';
import { downloadTablePDF } from '../../lib/pdf';

// Tipos de ausência e respetivas cores
const leaveTypes = {
  ferias: { label: 'Férias', cell: 'bg-blue-500', badge: 'bg-blue-100 text-blue-700 border-blue-300' },
  falta: { label: 'Falta', cell: 'bg-red-500', badge: 'bg-red-100 text-red-700 border-red-300' },
  doenca: { label: 'Doença', cell: 'bg-orange-500', badge: 'bg-orange-100 text-orange-700 border-orange-300' },
  folga: { label: 'Folga', cell: 'bg-purple-500', badge: 'bg-purple-100 text-purple-700 border-purple-300' },
  ausencia: { label: 'Ausência', cell: 'bg-slate-500', badge: 'bg-slate-100 text-slate-700 border-slate-300' },
};

const toKey = (d) => format(d, 'yyyy-MM-dd');

export default function AdminVacationMap() {
  const { selectedCompany } = useOutletContext();
  const [refDate, setRefDate] = useState(new Date());
  const [employees, setEmployees] = useState([]);
  const [leaves, setLeaves] = useState([]);
  const [balance, setBalance] = useState({});
  const [loading, setLoading] = useState(true);

  const month = refDate.getMonth() + 1;
  const year = refDate.getFullYear();

  const days = useMemo(
    () => eachDayOfInterval({ start: startOfMonth(refDate), end: endOfMonth(refDate) }),
    [refDate]
  );

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompany, month, year]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [leavesRes, employeesRes, balanceRes] = await Promise.all([
        getCalendarLeaves({ company_id: selectedCompany?.id, month, year }),
        getEmployees({ company_id: selectedCompany?.id }),
        getVacationBalance({ company_id: selectedCompany?.id, year }),
      ]);
      setLeaves(leavesRes.data || []);
      setEmployees(employeesRes.data || []);
      const balMap = {};
      for (const b of balanceRes.data || []) balMap[b.employee_id] = b;
      setBalance(balMap);
    } catch (error) {
      toast.error('Erro ao carregar o mapa de férias');
    } finally {
      setLoading(false);
    }
  };

  // Mapa: employee_id -> { 'yyyy-MM-dd' -> leave_type }
  const leaveByEmployeeDay = useMemo(() => {
    const map = {};
    for (const lv of leaves) {
      const start = parseISO(lv.start_date);
      const end = parseISO(lv.end_date);
      const range = eachDayOfInterval({ start, end });
      for (const d of range) {
        const k = toKey(d);
        if (!map[lv.employee_id]) map[lv.employee_id] = {};
        map[lv.employee_id][k] = lv.leave_type;
      }
    }
    return map;
  }, [leaves]);

  // Conta dias de ausência no mês visível por colaborador
  const countDays = (empId) => {
    const byDay = leaveByEmployeeDay[empId] || {};
    return days.filter((d) => byDay[toKey(d)]).length;
  };

  const handleExportPDF = () => {
    if (leaves.length === 0) {
      toast.error('Sem ausências para exportar neste mês');
      return;
    }
    const empName = (id) => employees.find((e) => e.id === id)?.name || '—';
    const rows = [...leaves]
      .sort((a, b) => (a.start_date || '').localeCompare(b.start_date || ''))
      .map((lv) => {
        const dias = lv.counted_days ?? (differenceInCalendarDays(parseISO(lv.end_date), parseISO(lv.start_date)) + 1);
        return [
          lv.employee_name || empName(lv.employee_id),
          (leaveTypes[lv.leave_type] || {}).label || lv.leave_type,
          format(parseISO(lv.start_date), 'dd/MM/yyyy'),
          format(parseISO(lv.end_date), 'dd/MM/yyyy'),
          dias,
        ];
      });
    const balanceRows = employees.map((e) => {
      const b = balance[e.id];
      return b ? [e.name, b.vacation_days, b.used, b.pending, b.available] : [e.name, '—', '—', '—', '—'];
    });
    downloadTablePDF({
      filename: `mapa-ferias-${year}-${String(month).padStart(2, '0')}${selectedCompany?.name ? '-' + selectedCompany.name : ''}.pdf`,
      title: 'Mapa de Férias',
      meta: [
        `Empresa: ${selectedCompany?.name || 'Todas as empresas'}`,
        `Mês: ${format(refDate, "MMMM 'de' yyyy", { locale: pt })}`,
      ],
      headers: ['Colaborador', 'Tipo', 'Início', 'Fim', 'Dias úteis'],
      rows,
      footerNote: 'RH grupo Lisbonb',
      extraTable: {
        title: `Saldo anual de férias — ${year}`,
        headers: ['Colaborador', 'Direito', 'Tirados', 'Pendentes', 'Restantes'],
        rows: balanceRows,
      },
    });
    toast.success('PDF gerado');
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-vacation-map-page">
      <PageHeader
        icon={CalendarRange}
        title="Mapa de Férias"
        subtitle={selectedCompany ? `Equipa de ${selectedCompany.name}` : 'Visão geral da equipa'}
      >
        <Button variant="outline" size="icon" onClick={() => setRefDate(subMonths(refDate, 1))} data-testid="prev-month-btn">
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="min-w-[140px] text-center font-medium capitalize">
          {format(refDate, "MMMM 'de' yyyy", { locale: pt })}
        </span>
        <Button variant="outline" size="icon" onClick={() => setRefDate(addMonths(refDate, 1))} data-testid="next-month-btn">
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button onClick={handleExportPDF} data-testid="export-vacation-pdf-btn">
          <FileText className="h-4 w-4 mr-2" />
          Exportar PDF
        </Button>
      </PageHeader>

      {/* Legenda */}
      <div className="flex flex-wrap gap-2">
        {Object.entries(leaveTypes).map(([key, t]) => (
          <Badge key={key} variant="outline" className={t.badge}>
            {t.label}
          </Badge>
        ))}
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : employees.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CalendarRange className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem colaboradores</h3>
              <p className="text-sm text-muted-foreground mt-1">Selecione uma empresa com colaboradores</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 bg-card text-left p-2 min-w-[160px] border-b border-r">
                      Colaborador
                    </th>
                    {days.map((d) => (
                      <th
                        key={toKey(d)}
                        className={`p-1 w-7 text-center text-xs font-medium border-b ${
                          isWeekend(d) ? 'bg-muted text-muted-foreground' : ''
                        }`}
                      >
                        {format(d, 'd')}
                      </th>
                    ))}
                    <th className="p-2 text-center border-b border-l min-w-[56px]">Dias (mês)</th>
                    <th className="p-2 text-center border-b border-l min-w-[60px]">Direito</th>
                    <th className="p-2 text-center border-b min-w-[72px]">Tirados {year}</th>
                    <th className="p-2 text-center border-b min-w-[76px]">Pendentes</th>
                    <th className="p-2 text-center border-b min-w-[76px]">Restantes</th>
                  </tr>
                </thead>
                <tbody>
                  {employees.map((emp) => {
                    const byDay = leaveByEmployeeDay[emp.id] || {};
                    const total = countDays(emp.id);
                    const bal = balance[emp.id];
                    return (
                      <tr key={emp.id} data-testid={`vacation-row-${emp.id}`}>
                        <td className="sticky left-0 z-10 bg-card p-2 font-medium border-b border-r truncate max-w-[160px]">
                          {emp.name}
                        </td>
                        {days.map((d) => {
                          const type = byDay[toKey(d)];
                          const cfg = type ? leaveTypes[type] : null;
                          return (
                            <td
                              key={toKey(d)}
                              className={`h-8 border-b text-center ${isWeekend(d) ? 'bg-muted/50' : ''}`}
                              title={cfg ? `${emp.name} — ${cfg.label} (${format(d, 'dd/MM')})` : ''}
                            >
                              {cfg && <div className={`mx-auto h-5 w-5 rounded ${cfg.cell}`} />}
                            </td>
                          );
                        })}
                        <td className="p-2 text-center border-b border-l font-medium">{total || '—'}</td>
                        <td className="p-2 text-center border-b border-l">{bal ? bal.vacation_days : '—'}</td>
                        <td className="p-2 text-center border-b font-medium">{bal ? bal.used : '—'}</td>
                        <td className={`p-2 text-center border-b ${bal && bal.pending > 0 ? 'text-amber-600 font-medium' : 'text-muted-foreground'}`}>
                          {bal && bal.pending > 0 ? bal.pending : '—'}
                        </td>
                        <td className={`p-2 text-center border-b font-semibold ${bal && bal.available < 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                          {bal ? bal.available : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
