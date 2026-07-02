// Lembrete de ponto por notificação LOCAL (agendada no próprio telemóvel).
// Funciona sem internet. Só faz algo na app nativa (Capacitor).
import { Capacitor } from '@capacitor/core';
import { LocalNotifications } from '@capacitor/local-notifications';

// work_days do backend: 0=Seg ... 6=Dom.
// LocalNotifications usa weekday 1=Domingo ... 7=Sábado. Conversão:
const toLnWeekday = (d) => (d === 6 ? 1 : d + 2); // Dom(6)->1, Seg(0)->2, ... Sáb(5)->7

// Um id fixo por dia da semana (para poder atualizar/cancelar sem duplicar).
const REMINDER_IDS = [1000, 1001, 1002, 1003, 1004, 1005, 1006];

// Pede a permissão de notificações (usado no onboarding, à entrada da app).
// Só na app nativa; falha em silêncio.
export async function requestNotificationPermission() {
  if (!Capacitor.isNativePlatform()) return;
  try {
    const perm = await LocalNotifications.checkPermissions();
    if (perm.display !== 'granted') {
      await LocalNotifications.requestPermissions();
    }
  } catch { /* ignora */ }
}

/**
 * Agenda (ou limpa) o lembrete de ponto, 5 min antes do início do turno,
 * nos dias de trabalho da escala. Repete todas as semanas.
 * @returns {Promise<{ok:boolean, reason?:string, at?:string, count?:number}>}
 */
export async function syncShiftReminders(workDays, startTime, minutesBefore = 5) {
  if (!Capacitor.isNativePlatform()) return { ok: false, reason: 'web' };

  // Limpar sempre os anteriores (evita duplicados e reflete mudanças de escala)
  try {
    await LocalNotifications.cancel({ notifications: REMINDER_IDS.map((id) => ({ id })) });
  } catch { /* sem lembretes antigos, tudo bem */ }

  if (!startTime || !Array.isArray(workDays) || workDays.length === 0) {
    return { ok: false, reason: 'no-schedule' };
  }

  // Permissão de notificações
  let perm = await LocalNotifications.checkPermissions();
  if (perm.display !== 'granted') {
    perm = await LocalNotifications.requestPermissions();
    if (perm.display !== 'granted') return { ok: false, reason: 'denied' };
  }

  // Hora do lembrete = início − minutesBefore
  const [h, m] = String(startTime).split(':').map(Number);
  let total = h * 60 + m - minutesBefore;
  if (total < 0) total += 1440; // caso raro (turno logo após a meia-noite)
  const hour = Math.floor(total / 60);
  const minute = total % 60;

  const notifications = workDays.map((d) => ({
    id: 1000 + d,
    title: 'Lembrete de ponto',
    body: `O teu turno começa daqui a ${minutesBefore} minutos. Não te esqueças de dar entrada! 📲`,
    schedule: { on: { weekday: toLnWeekday(d), hour, minute }, allowWhileIdle: true },
  }));

  await LocalNotifications.schedule({ notifications });
  const at = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
  return { ok: true, count: notifications.length, at };
}
