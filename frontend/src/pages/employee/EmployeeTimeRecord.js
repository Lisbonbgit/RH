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
import { Clock, LogIn, LogOut, History, MapPin, Loader2, CheckCircle2, AlertTriangle, X } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO, isToday } from 'date-fns';
import { pt } from 'date-fns/locale';
// Localização web + nativa (app Capacitor) num só sítio.
import { getCurrentPositionSmart, geoHelpMessage } from '../../lib/geo';

export default function EmployeeTimeRecord() {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [locating, setLocating] = useState(false);
  const [confirmType, setConfirmType] = useState(null);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [feedback, setFeedback] = useState(null); // aviso visível no ecrã

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
    setFeedback(null);
    const label = type === 'entrada' ? 'Entrada' : 'Saída';
    try {
      // Tenta obter a localização (não bloqueia o registo se o local não exigir)
      setLocating(true);
      const { position, errorCode } = await getCurrentPositionSmart();
      setLocating(false);

      await createTimeRecord({ record_type: type, ...(position || {}) });

      if (position) {
        toast.success(`${label} registada com localização!`);
        setFeedback({ kind: 'success', title: `${label} registada`, description: 'Com a sua localização. ✅' });
      } else {
        toast.success(`${label} registada (sem localização)`);
        setFeedback({ kind: 'success', title: `${label} registada`, description: 'Este local não exige localização.' });
      }
      fetchRecords();
    } catch (error) {
      const status = error.response?.status;
      const detail = error.response?.data?.detail;
      if (status === 400 && /localiza/i.test(detail || '')) {
        // Loja com cerca e sem localização obtida (permissão/GPS)
        const m = geoHelpMessage(errorCode);
        toast.error(m.title, { description: m.description, duration: 11000 });
        setFeedback({ kind: 'error', title: m.title, description: m.description });
      } else if (status === 403) {
        // Está fora do raio permitido do local
        toast.error(detail || 'Está fora do local de trabalho');
        setFeedback({ kind: 'error', title: 'Fora do local de trabalho', description: detail || 'Aproxime-se do local para registar o ponto.' });
      } else {
        toast.error(detail || 'Erro ao registar ponto');
        setFeedback({ kind: 'error', title: 'Não foi possível registar', description: detail || 'Tente novamente dentro de momentos.' });
      }
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

      {/* Aviso visível do resultado do registo (bem visível no telemóvel) */}
      {feedback && (
        <div
          className={`rounded-xl border p-4 flex items-start gap-3 ${
            feedback.kind === 'success'
              ? 'bg-green-50 border-green-200 text-green-800'
              : 'bg-red-50 border-red-200 text-red-800'
          }`}
          data-testid="record-feedback"
        >
          {feedback.kind === 'success' ? (
            <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5" />
          ) : (
            <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
          )}
          <div className="flex-1 min-w-0">
            <p className="font-semibold">{feedback.title}</p>
            {feedback.description && <p className="text-sm mt-0.5">{feedback.description}</p>}
          </div>
          <button onClick={() => setFeedback(null)} className="shrink-0 opacity-60 hover:opacity-100" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>
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
