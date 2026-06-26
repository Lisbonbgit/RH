import React, { useState, useEffect } from 'react';
import { getTimeRecords, createTimeRecord } from '../../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import { Clock, LogIn, LogOut, History, MapPin, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO, isToday } from 'date-fns';
import { pt } from 'date-fns/locale';

// Obtém a posição atual do browser. Devolve null se o utilizador negar ou não suportar.
function getCurrentPosition() {
  return new Promise((resolve) => {
    if (!('geolocation' in navigator)) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
      }),
      () => resolve(null), // negado / erro: regista na mesma, sem localização
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
    );
  });
}

export default function EmployeeTimeRecord() {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [locating, setLocating] = useState(false);
  const [confirmType, setConfirmType] = useState(null);
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
      // Tenta obter a localização (não bloqueia o registo se for negada)
      setLocating(true);
      const position = await getCurrentPosition();
      setLocating(false);

      await createTimeRecord({ record_type: type, ...(position || {}) });

      if (position) {
        toast.success(`${type === 'entrada' ? 'Entrada' : 'Saída'} registada com localização!`);
      } else {
        toast.success(`${type === 'entrada' ? 'Entrada' : 'Saída'} registada (sem localização)`);
      }
      fetchRecords();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao registar ponto');
    } finally {
      setSubmitting(false);
      setLocating(false);
    }
  };

  const todayRecords = records.filter((r) => isToday(parseISO(r.time)));

  const LocationLink = ({ record }) =>
    record.latitude != null && record.longitude != null ? (
      <a
        href={`https://www.google.com/maps?q=${record.latitude},${record.longitude}`}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        title={`Precisão ~${Math.round(record.accuracy || 0)}m`}
      >
        <MapPin className="h-3 w-3" /> Ver no mapa
      </a>
    ) : null;

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
          onClick={() => setConfirmType('entrada')}
          disabled={submitting}
          data-testid="entrada-btn"
        >
          <LogIn className="h-8 w-8" />
          <span className="text-lg font-medium">Entrada</span>
        </Button>
        <Button
          size="lg"
          className="h-24 flex-col gap-2 bg-red-600 hover:bg-red-700"
          onClick={() => setConfirmType('saida')}
          disabled={submitting}
          data-testid="saida-btn"
        >
          <LogOut className="h-8 w-8" />
          <span className="text-lg font-medium">Saída</span>
        </Button>
      </div>

      {locating && (
        <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> A obter a sua localização…
        </p>
      )}

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
                    <LocationLink record={record} />
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
                    <LocationLink record={record} />
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

      <AlertDialog open={confirmType !== null} onOpenChange={(open) => !open && setConfirmType(null)}>
        <AlertDialogContent data-testid="confirm-record-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>
              Confirmar {confirmType === 'entrada' ? 'entrada' : 'saída'}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Vai registar a sua <strong>{confirmType === 'entrada' ? 'entrada' : 'saída'}</strong> às{' '}
              {format(currentTime, 'HH:mm')}. Confirma?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="confirm-record-cancel">Cancelar</AlertDialogCancel>
            <AlertDialogAction
              className={confirmType === 'entrada' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'}
              onClick={() => {
                const t = confirmType;
                setConfirmType(null);
                handleRecord(t);
              }}
              data-testid="confirm-record-action"
            >
              Sim, registar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
