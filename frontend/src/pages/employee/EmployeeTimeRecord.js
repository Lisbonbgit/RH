import React, { useState, useEffect } from 'react';
import { getTimeRecords, createTimeRecord } from '../../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { Clock, LogIn, LogOut, History } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO, isToday } from 'date-fns';
import { pt } from 'date-fns/locale';

export default function EmployeeTimeRecord() {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    fetchRecords();
    const interval = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const fetchRecords = async () => {
    setLoading(true);
    try {
      const response = await getTimeRecords();
      setRecords(response.data);
    } catch (error) {
      toast.error('Erro ao carregar registos');
    } finally {
      setLoading(false);
    }
  };

  const handleRecord = async (type) => {
    setSubmitting(true);
    try {
      await createTimeRecord({ record_type: type });
      toast.success(`${type === 'entrada' ? 'Entrada' : 'Saída'} registada com sucesso!`);
      fetchRecords();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao registar ponto');
    } finally {
      setSubmitting(false);
    }
  };

  const todayRecords = records.filter(r => isToday(parseISO(r.time)));
  const lastRecord = todayRecords[0];

  return (
    <div className="space-y-6 animate-fade-in pb-4" data-testid="employee-time-record-page">
      {/* Clock Display */}
      <Card className="bg-primary text-primary-foreground">
        <CardContent className="p-6 text-center">
          <p className="text-sm text-primary-foreground/80 mb-2">
            {format(currentTime, "EEEE, d 'de' MMMM 'de' yyyy", { locale: pt })}
          </p>
          <p className="text-5xl font-heading font-bold tracking-tight">
            {format(currentTime, 'HH:mm:ss')}
          </p>
        </CardContent>
      </Card>

      {/* Record Buttons */}
      <div className="grid grid-cols-2 gap-4">
        <Button
          size="lg"
          className="h-24 flex-col gap-2 bg-green-600 hover:bg-green-700"
          onClick={() => handleRecord('entrada')}
          disabled={submitting}
          data-testid="entrada-btn"
        >
          <LogIn className="h-8 w-8" />
          <span className="text-lg font-medium">Entrada</span>
        </Button>
        <Button
          size="lg"
          className="h-24 flex-col gap-2 bg-red-600 hover:bg-red-700"
          onClick={() => handleRecord('saida')}
          disabled={submitting}
          data-testid="saida-btn"
        >
          <LogOut className="h-8 w-8" />
          <span className="text-lg font-medium">Saída</span>
        </Button>
      </div>

      {/* Today's Records */}
      <Card data-testid="today-records-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Registos de Hoje
          </CardTitle>
        </CardHeader>
        <CardContent>
          {todayRecords.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              Ainda não registou ponto hoje
            </p>
          ) : (
            <div className="space-y-2">
              {todayRecords.map((record) => (
                <div key={record.id} className="flex items-center justify-between p-3 bg-muted rounded-lg">
                  <div className="flex items-center gap-3">
                    <Badge variant={record.record_type === 'entrada' ? 'default' : 'secondary'}>
                      {record.record_type === 'entrada' ? 'Entrada' : 'Saída'}
                    </Badge>
                    <span className="font-medium">
                      {format(parseISO(record.time), 'HH:mm')}
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
          )}
        </CardContent>
      </Card>

      {/* History */}
      <Card data-testid="history-records-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <History className="h-4 w-4" />
            Histórico de Registos
          </CardTitle>
          <CardDescription>Últimos 20 registos</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center h-20">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : records.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              Sem registos de ponto
            </p>
          ) : (
            <div className="space-y-2">
              {records.slice(0, 20).map((record) => (
                <div key={record.id} className="flex items-center justify-between p-3 bg-muted rounded-lg">
                  <div className="flex items-center gap-3">
                    <Badge variant={record.record_type === 'entrada' ? 'default' : 'secondary'}>
                      {record.record_type === 'entrada' ? 'Entrada' : 'Saída'}
                    </Badge>
                    <span className="text-sm">
                      {format(parseISO(record.time), "dd/MM/yyyy 'às' HH:mm", { locale: pt })}
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}
