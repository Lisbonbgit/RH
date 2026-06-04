import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getEmployees, getSchedules, createSchedule, getScheduleAssignments, assignSchedule } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Checkbox } from '../../components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { CalendarDays, Plus } from 'lucide-react';
import { toast } from 'sonner';

const weekDays = [
  { value: 0, label: 'Seg' },
  { value: 1, label: 'Ter' },
  { value: 2, label: 'Qua' },
  { value: 3, label: 'Qui' },
  { value: 4, label: 'Sex' },
  { value: 5, label: 'Sáb' },
  { value: 6, label: 'Dom' }
];

const formatWorkDays = (days) => {
  if (!Array.isArray(days) || days.length === 0) return '-';
  return weekDays
    .filter((day) => days.includes(day.value))
    .map((day) => day.label)
    .join(', ');
};

export default function AdminSchedules() {
  const { selectedCompany } = useOutletContext();
  const [templates, setTemplates] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [savingAssignment, setSavingAssignment] = useState(false);

  const [templateForm, setTemplateForm] = useState({
    name: '',
    workDays: [0, 1, 2, 3, 4]
  });

  const [assignmentForm, setAssignmentForm] = useState({
    employeeId: '',
    templateId: '',
    startDate: '',
    endDate: ''
  });

  useEffect(() => {
    fetchData();
  }, [selectedCompany]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [templatesRes, assignmentsRes, employeesRes] = await Promise.all([
        getSchedules(),
        getScheduleAssignments(),
        getEmployees({ company_id: selectedCompany?.id })
      ]);
      setTemplates(templatesRes.data);
      setAssignments(assignmentsRes.data);
      setEmployees(employeesRes.data);
    } catch (error) {
      toast.error('Erro ao carregar escalas');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleWorkDay = (dayValue) => {
    setTemplateForm((prev) => {
      const exists = prev.workDays.includes(dayValue);
      const nextDays = exists
        ? prev.workDays.filter((day) => day !== dayValue)
        : [...prev.workDays, dayValue].sort();
      return { ...prev, workDays: nextDays };
    });
  };

  const handleCreateTemplate = async (e) => {
    e.preventDefault();
    if (!templateForm.name.trim()) {
      toast.error('Informe o nome da escala');
      return;
    }
    if (!templateForm.workDays.length) {
      toast.error('Selecione pelo menos um dia de trabalho');
      return;
    }
    setSavingTemplate(true);
    try {
      const response = await createSchedule({
        name: templateForm.name,
        workDays: templateForm.workDays
      });
      toast.success('Escala criada com sucesso');
      setTemplates((prev) => [response.data, ...prev]);
      setTemplateForm({ name: '', workDays: templateForm.workDays });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao criar escala');
    } finally {
      setSavingTemplate(false);
    }
  };

  const handleAssignSchedule = async (e) => {
    e.preventDefault();
    if (!assignmentForm.employeeId || !assignmentForm.templateId) {
      toast.error('Selecione colaborador e escala');
      return;
    }
    if (!assignmentForm.startDate) {
      toast.error('Defina a data de início');
      return;
    }
    if (assignmentForm.endDate && assignmentForm.startDate > assignmentForm.endDate) {
      toast.error('Data de início não pode ser posterior à data de fim');
      return;
    }

    setSavingAssignment(true);
    try {
      const response = await assignSchedule({
        employeeId: assignmentForm.employeeId,
        templateId: assignmentForm.templateId,
        startDate: assignmentForm.startDate,
        endDate: assignmentForm.endDate || null
      });
      toast.success('Escala atribuída com sucesso');
      setAssignments((prev) => [response.data, ...prev]);
      setAssignmentForm({
        employeeId: '',
        templateId: '',
        startDate: '',
        endDate: ''
      });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao atribuir escala');
    } finally {
      setSavingAssignment(false);
    }
  };

  const assignmentRows = useMemo(() => {
    if (!selectedCompany) return assignments;
    const employeeIds = new Set(employees.map((emp) => emp.id));
    return assignments.filter((assignment) => employeeIds.has(assignment.employee_id));
  }, [assignments, employees, selectedCompany]);

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-schedules-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-heading font-bold">Escalas</h1>
        <p className="text-muted-foreground mt-1">
          {selectedCompany ? `Escalas de ${selectedCompany.name}` : 'Definir escalas e atribuições por colaborador'}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card data-testid="schedule-create-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5" />
              Criar Escala
            </CardTitle>
            <CardDescription>Defina os dias trabalhados no ciclo semanal.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateTemplate} className="space-y-4" data-testid="schedule-create-form">
              <div className="space-y-2">
                <Label htmlFor="schedule-name" data-testid="schedule-name-label">Nome da escala</Label>
                <Input
                  id="schedule-name"
                  value={templateForm.name}
                  onChange={(e) => setTemplateForm({ ...templateForm, name: e.target.value })}
                  placeholder="Ex: 5x2 (Seg-Sex)"
                  data-testid="schedule-name-input"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label data-testid="schedule-days-label">Dias trabalhados</Label>
                <div className="flex flex-wrap gap-3" data-testid="schedule-days-options">
                  {weekDays.map((day) => (
                    <label key={day.value} className="flex items-center gap-2 text-sm" data-testid={`schedule-day-${day.value}`}>
                      <Checkbox
                        checked={templateForm.workDays.includes(day.value)}
                        onCheckedChange={() => handleToggleWorkDay(day.value)}
                        data-testid={`schedule-day-checkbox-${day.value}`}
                      />
                      {day.label}
                    </label>
                  ))}
                </div>
              </div>
              <Button type="submit" disabled={savingTemplate} data-testid="schedule-create-btn">
                {savingTemplate ? 'A guardar...' : 'Guardar Escala'}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card data-testid="schedule-assign-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Plus className="h-5 w-5" />
              Atribuir Escala
            </CardTitle>
            <CardDescription>Associar escala a um colaborador por período.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAssignSchedule} className="space-y-4" data-testid="schedule-assign-form">
              <div className="space-y-2">
                <Label data-testid="schedule-assign-employee-label">Colaborador</Label>
                <Select
                  value={assignmentForm.employeeId || '__empty__'}
                  onValueChange={(value) => setAssignmentForm({ ...assignmentForm, employeeId: value === '__empty__' ? '' : value })}
                >
                  <SelectTrigger data-testid="schedule-assign-employee-select">
                    <SelectValue placeholder="Selecionar colaborador" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__empty__">Selecionar colaborador</SelectItem>
                    {employees.map((employee) => (
                      <SelectItem key={employee.id} value={employee.id}>
                        {employee.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label data-testid="schedule-assign-template-label">Escala</Label>
                <Select
                  value={assignmentForm.templateId || '__empty__'}
                  onValueChange={(value) => setAssignmentForm({ ...assignmentForm, templateId: value === '__empty__' ? '' : value })}
                >
                  <SelectTrigger data-testid="schedule-assign-template-select">
                    <SelectValue placeholder="Selecionar escala" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__empty__">Selecionar escala</SelectItem>
                    {templates.map((template) => (
                      <SelectItem key={template.id} value={template.id}>
                        {template.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="schedule-start" data-testid="schedule-assign-start-label">Início</Label>
                  <Input
                    id="schedule-start"
                    type="date"
                    value={assignmentForm.startDate}
                    onChange={(e) => setAssignmentForm({ ...assignmentForm, startDate: e.target.value })}
                    required
                    data-testid="schedule-assign-start-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="schedule-end" data-testid="schedule-assign-end-label">Fim (opcional)</Label>
                  <Input
                    id="schedule-end"
                    type="date"
                    value={assignmentForm.endDate}
                    onChange={(e) => setAssignmentForm({ ...assignmentForm, endDate: e.target.value })}
                    data-testid="schedule-assign-end-input"
                  />
                </div>
              </div>
              <Button type="submit" disabled={savingAssignment} data-testid="schedule-assign-btn">
                {savingAssignment ? 'A atribuir...' : 'Atribuir Escala'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card data-testid="schedule-list-card">
        <CardHeader>
          <CardTitle>Escalas Criadas</CardTitle>
          <CardDescription>Lista de escalas disponíveis para atribuição.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : templates.length === 0 ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              Nenhuma escala criada ainda.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Escala</TableHead>
                    <TableHead>Dias Trabalhados</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {templates.map((template) => (
                    <TableRow key={template.id} data-testid={`schedule-row-${template.id}`}>
                      <TableCell className="font-medium">{template.name}</TableCell>
                      <TableCell data-testid={`schedule-days-${template.id}`}>{formatWorkDays(template.work_days)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card data-testid="schedule-assignments-card">
        <CardHeader>
          <CardTitle>Histórico de Atribuições</CardTitle>
          <CardDescription>Períodos de escala atribuídos por colaborador.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : assignmentRows.length === 0 ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              Nenhuma atribuição registrada.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Colaborador</TableHead>
                    <TableHead>Escala</TableHead>
                    <TableHead>Período</TableHead>
                    <TableHead>Dias Trabalhados</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {assignmentRows.map((assignment) => (
                    <TableRow key={assignment.id} data-testid={`assignment-row-${assignment.id}`}>
                      <TableCell className="font-medium">{assignment.employee_name || '-'}</TableCell>
                      <TableCell>{assignment.template_name || '-'}</TableCell>
                      <TableCell data-testid={`assignment-period-${assignment.id}`}>
                        {assignment.start_date} 
                        {assignment.end_date ? `até ${assignment.end_date}` : 'até Atual'}
                      </TableCell>
                      <TableCell data-testid={`assignment-days-${assignment.id}`}>{formatWorkDays(assignment.work_days)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
