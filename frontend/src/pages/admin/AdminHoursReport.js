import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getWorkedHoursReport, getEmployees } from '../../lib/api';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Badge } from '../../components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { Clock4, Filter, Download, FileText, AlertTriangle } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { toast } from 'sonner';
import { format, startOfMonth } from 'date-fns';
import { downloadCSV } from '../../lib/export';
import { downloadTablePDF } from '../../lib/pdf';

// Converte horas decimais (ex.: 7.5) em "7h30"
function formatHours(h) {
  const totalMin = Math.round((h || 0) * 60);
  const hours = Math.floor(totalMin / 60);
  const mins = totalMin % 60;
  return `${hours}h${String(mins).padStart(2, '0')}`;
}

export default function AdminHoursReport() {
  const { selectedCompany } = useOutletContext();
  const [report, setReport] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    employee_id: '',
    start_date: format(startOfMonth(new Date()), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  });

  useEffect(() => {
    getEmployees({ company_id: selectedCompany?.id })
      .then((res) => setEmployees(res.data || []))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompany]);

  useEffect(() => {
    fetchReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompany, filters]);

  const fetchReport = async () => {
    setLoading(true);
    try {
      const params = { company_id: selectedCompany?.id, ...filters };
      Object.keys(params).forEach((k) => !params[k] && delete params[k]);
      const res = await getWorkedHoursReport(params);
      setReport(res.data || []);
    } catch (error) {
      toast.error('Erro ao gerar o relatório');
    } finally {
      setLoading(false);
    }
  };

  const totalHours = report.reduce((sum, r) => sum + (r.total_hours || 0), 0);

  const handleExport = () => {
    if (report.length === 0) {
      toast.error('Sem dados para exportar');
      return;
    }
    const headers = ['Colaborador', 'Dias trabalhados', 'Total de horas', 'Horas (decimal)', 'Estado'];
    const rows = report.map((r) => [
      r.employee_name,
      r.days_worked,
      formatHours(r.total_hours),
      String(r.total_hours).replace('.', ','),
      r.incomplete ? 'Registos incompletos' : 'Completo',
    ]);
    const suffix = selectedCompany?.name ? `-${selectedCompany.name}` : '';
    downloadCSV(`horas-${filters.start_date}-a-${filters.end_date}${suffix}.csv`, headers, rows);
    toast.success('Relatório exportado');
  };

  const handleExportPDF = () => {
    if (report.length === 0) {
      toast.error('Sem dados para exportar');
      return;
    }
    const headers = ['Colaborador', 'Dias', 'Total de horas', 'Estado'];
    const rows = report.map((r) => [
      r.employee_name,
      r.days_worked,
      formatHours(r.total_hours),
      r.incomplete ? 'Registos incompletos' : 'Completo',
    ]);
    const meta = [
      `Empresa: ${selectedCompany?.name || 'Todas as empresas'}`,
      `Período: ${format(new Date(filters.start_date), 'dd/MM/yyyy')} a ${format(new Date(filters.end_date), 'dd/MM/yyyy')}`,
    ];
    const suffix = selectedCompany?.name ? `-${selectedCompany.name}` : '';
    downloadTablePDF({
      filename: `horas-${filters.start_date}-a-${filters.end_date}${suffix}.pdf`,
      title: 'Relatório de Horas',
      meta,
      headers,
      rows,
      foot: ['Total', '', formatHours(totalHours), ''],
      footerNote: 'RH grupo Lisbonb',
    });
    toast.success('PDF gerado');
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-hours-report-page">
      <PageHeader
        icon={Clock4}
        title="Relatório de Horas"
        subtitle={selectedCompany ? `Horas trabalhadas em ${selectedCompany.name}` : 'Horas trabalhadas por colaborador'}
      >
        <Button variant="outline" onClick={handleExport} data-testid="export-hours-btn">
          <Download className="h-4 w-4 mr-2" />
          Exportar CSV
        </Button>
        <Button onClick={handleExportPDF} data-testid="export-hours-pdf-btn">
          <FileText className="h-4 w-4 mr-2" />
          Exportar PDF
        </Button>
      </PageHeader>

      {/* Filtros */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 mb-4">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">Período</span>
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
              <Label>Data Início</Label>
              <Input
                type="date"
                value={filters.start_date}
                onChange={(e) => setFilters({ ...filters, start_date: e.target.value })}
                data-testid="filter-start-date"
              />
            </div>
            <div className="space-y-2">
              <Label>Data Fim</Label>
              <Input
                type="date"
                value={filters.end_date}
                onChange={(e) => setFilters({ ...filters, end_date: e.target.value })}
                data-testid="filter-end-date"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Total */}
      {!loading && report.length > 0 && (
        <Card className="bg-primary text-primary-foreground">
          <CardContent className="p-4 flex items-center justify-between">
            <span className="text-sm text-primary-foreground/80">Total de horas no período</span>
            <span className="text-2xl font-heading font-bold">{formatHours(totalHours)}</span>
          </CardContent>
        </Card>
      )}

      {/* Tabela */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : report.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Clock4 className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem dados</h3>
              <p className="text-sm text-muted-foreground mt-1">Sem registos de ponto no período selecionado</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Colaborador</TableHead>
                    <TableHead className="text-center">Dias</TableHead>
                    <TableHead className="text-right">Total de Horas</TableHead>
                    <TableHead className="text-right hidden sm:table-cell">Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.map((r) => (
                    <TableRow key={r.employee_id} data-testid={`hours-row-${r.employee_id}`}>
                      <TableCell className="font-medium">{r.employee_name}</TableCell>
                      <TableCell className="text-center">{r.days_worked}</TableCell>
                      <TableCell className="text-right font-semibold">{formatHours(r.total_hours)}</TableCell>
                      <TableCell className="text-right hidden sm:table-cell">
                        {r.incomplete ? (
                          <Badge variant="outline" className="text-yellow-600 border-yellow-300 gap-1">
                            <AlertTriangle className="h-3 w-3" /> Incompleto
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-green-600 border-green-300">
                            Completo
                          </Badge>
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

      <p className="text-xs text-muted-foreground">
        "Incompleto" indica entradas sem a saída correspondente (ou vice-versa) no período — corrija no Controlo de Ponto para um cálculo exato.
      </p>
    </div>
  );
}
