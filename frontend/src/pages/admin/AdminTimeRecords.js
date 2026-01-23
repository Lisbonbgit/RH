import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getTimeRecords, correctTimeRecord, getEmployees } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Textarea } from '../../components/ui/textarea';
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { Clock, Pencil, Filter, History } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';

export default function AdminTimeRecords() {
  const { selectedCompany } = useOutletContext();
  const [records, setRecords] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [filters, setFilters] = useState({
    employee_id: '',
    start_date: '',
    end_date: ''
  });
  const [correctionData, setCorrectionData] = useState({
    time: '',
    justification: ''
  });
  const [saving, setSaving] = useState(false);

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
      
      const [recordsRes, employeesRes] = await Promise.all([
        getTimeRecords(params),
        getEmployees({ company_id: selectedCompany?.id })
      ]);
      setRecords(recordsRes.data);
      setEmployees(employeesRes.data);
    } catch (error) {
      toast.error('Erro ao carregar dados');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenCorrection = (record) => {
    setSelectedRecord(record);
    setCorrectionData({
      time: record.time.slice(0, 16),
      justification: ''
    });
    setDialogOpen(true);
  };

  const handleSubmitCorrection = async (e) => {
    e.preventDefault();
    if (!correctionData.justification.trim()) {
      toast.error('Justificação é obrigatória');
      return;
    }
    setSaving(true);
    try {
      await correctTimeRecord(selectedRecord.id, {
        time: new Date(correctionData.time).toISOString(),
        justification: correctionData.justification
      });
      toast.success('Ponto corrigido com sucesso');
      setDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao corrigir ponto');
    } finally {
      setSaving(false);
    }
  };

  const clearFilters = () => {
    setFilters({ employee_id: '', start_date: '', end_date: '' });
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-time-records-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-heading font-bold">Controlo de Ponto</h1>
        <p className="text-muted-foreground mt-1">
          {selectedCompany ? `Registos de ${selectedCompany.name}` : 'Visualizar e corrigir registos de ponto'}
        </p>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 mb-4">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">Filtros</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
            <div className="flex items-end">
              <Button variant="outline" onClick={clearFilters} className="w-full" data-testid="clear-filters-btn">
                Limpar Filtros
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Records Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : records.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Clock className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem registos</h3>
              <p className="text-sm text-muted-foreground mt-1">Nenhum registo de ponto encontrado</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Colaborador</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Data/Hora</TableHead>
                    <TableHead className="hidden sm:table-cell">Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {records.map((record) => (
                    <TableRow key={record.id} data-testid={`record-row-${record.id}`}>
                      <TableCell className="font-medium">{record.employee_name}</TableCell>
                      <TableCell>
                        <Badge variant={record.record_type === 'entrada' ? 'default' : 'secondary'}>
                          {record.record_type === 'entrada' ? 'Entrada' : 'Saída'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {format(parseISO(record.time), "dd/MM/yyyy 'às' HH:mm", { locale: pt })}
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        {record.corrected ? (
                          <Badge variant="outline" className="text-yellow-600 border-yellow-300">
                            Corrigido
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-green-600 border-green-300">
                            Original
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleOpenCorrection(record)}
                            data-testid={`correct-record-${record.id}`}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          {record.correction_history?.length > 0 && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => {
                                setSelectedRecord(record);
                                setHistoryDialogOpen(true);
                              }}
                              data-testid={`history-record-${record.id}`}
                            >
                              <History className="h-4 w-4" />
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

      {/* Correction Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="correction-dialog">
          <DialogHeader>
            <DialogTitle>Corrigir Ponto</DialogTitle>
            <DialogDescription>
              Corrija o registo de ponto de {selectedRecord?.employee_name}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmitCorrection}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>Hora Original</Label>
                <p className="text-sm text-muted-foreground">
                  {selectedRecord && format(parseISO(selectedRecord.time), "dd/MM/yyyy 'às' HH:mm", { locale: pt })}
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="new_time">Nova Hora *</Label>
                <Input
                  id="new_time"
                  type="datetime-local"
                  value={correctionData.time}
                  onChange={(e) => setCorrectionData({ ...correctionData, time: e.target.value })}
                  required
                  data-testid="correction-time-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="justification">Justificação *</Label>
                <Textarea
                  id="justification"
                  value={correctionData.justification}
                  onChange={(e) => setCorrectionData({ ...correctionData, justification: e.target.value })}
                  placeholder="Motivo da correção"
                  rows={3}
                  required
                  data-testid="correction-justification-input"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving} data-testid="save-correction-btn">
                {saving ? 'A guardar...' : 'Corrigir'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* History Dialog */}
      <Dialog open={historyDialogOpen} onOpenChange={setHistoryDialogOpen}>
        <DialogContent data-testid="history-dialog">
          <DialogHeader>
            <DialogTitle>Histórico de Alterações</DialogTitle>
            <DialogDescription>
              Alterações feitas no registo de ponto
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4 max-h-80 overflow-y-auto">
            {selectedRecord?.correction_history?.map((entry, index) => (
              <div key={index} className="p-3 bg-muted rounded-lg space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">De:</span>
                  <span>{format(parseISO(entry.previous_time), "dd/MM/yyyy HH:mm")}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Para:</span>
                  <span className="font-medium">{format(parseISO(entry.new_time), "dd/MM/yyyy HH:mm")}</span>
                </div>
                <div className="text-sm">
                  <span className="text-muted-foreground">Motivo: </span>
                  <span>{entry.justification}</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {format(parseISO(entry.corrected_at), "dd/MM/yyyy 'às' HH:mm")}
                </div>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
