// Localização robusta para a WEB e para a APP nativa (Capacitor).
// - Na web: usa a Geolocation do browser, com fallback de precisão (Safari/iOS).
// - No telemóvel (app): usa o GPS NATIVO via plugin do Capacitor — mais fiável,
//   com o pedido de permissão próprio do sistema.
// Em ambos os casos devolve sempre { position, errorCode }:
//   position = { latitude, longitude, accuracy } ou null
//   errorCode = 1 (sem permissão) | 2 (indisponível) | 3 (timeout) | null
import { Capacitor } from '@capacitor/core';
import { Geolocation } from '@capacitor/geolocation';

// ---------- WEB ----------
function getPositionOnce(options) {
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        ok: true,
        position: { latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy },
      }),
      (err) => resolve({ ok: false, code: err.code }),
      options
    );
  });
}

async function getWebPosition() {
  if (!('geolocation' in navigator)) return { position: null, errorCode: null };
  // 1) alta precisão; 2) se falhar, precisão normal (mais fiável) e aceita fix recente
  let r = await getPositionOnce({ enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 });
  if (!r.ok) {
    r = await getPositionOnce({ enableHighAccuracy: false, timeout: 12000, maximumAge: 300000 });
  }
  return r.ok ? { position: r.position, errorCode: null } : { position: null, errorCode: r.code };
}

// ---------- NATIVO (app) ----------
// Timeout próprio: no Android, com a localização do telemóvel DESLIGADA, o
// getCurrentPosition pode ficar "pendurado" sem devolver erro. Assim garantimos
// sempre uma resposta e uma mensagem ao colaborador.
function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), ms)),
  ]);
}

async function getNativePosition() {
  try {
    let perm = await Geolocation.checkPermissions();
    if (perm.location !== 'granted') {
      perm = await Geolocation.requestPermissions();
      if (perm.location !== 'granted') {
        return { position: null, errorCode: 1 }; // permissão negada
      }
    }
    const pos = await withTimeout(
      Geolocation.getCurrentPosition({ enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }),
      12000
    );
    return {
      position: { latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy },
      errorCode: null,
    };
  } catch (e) {
    const msg = String((e && e.message) || '').toLowerCase();
    // permissão negada => 1; timeout/localização desligada/indisponível => 2
    if (msg.includes('denied') || msg.includes('permission')) return { position: null, errorCode: 1 };
    return { position: null, errorCode: 2 };
  }
}

// ---------- API pública ----------
export async function getCurrentPositionSmart() {
  return Capacitor.isNativePlatform() ? getNativePosition() : getWebPosition();
}

// Pede a permissão de localização (usado no onboarding, à entrada da app).
// Só na app nativa; falha em silêncio.
export async function requestLocationPermission() {
  if (!Capacitor.isNativePlatform()) return;
  try {
    const perm = await Geolocation.checkPermissions();
    if (perm.location !== 'granted') {
      await Geolocation.requestPermissions();
    }
  } catch { /* ignora */ }
}

// Mensagem de ajuda consoante o motivo da falha (adapta-se a app/web).
export function geoHelpMessage(code) {
  const isApp = Capacitor.isNativePlatform();
  if (code === 1) {
    return {
      title: 'Sem permissão de localização',
      description: isApp
        ? 'A app precisa de acesso à localização. Vá a Definições › Apps › Lisbonb RH › Permissões › Localização › "Permitir durante a utilização" e tente novamente.'
        : 'No iPhone: Definições › Privacidade › Serviços de Localização › Safari › "Ao usar a app". Depois, na barra toque em "AA" › Definições do Website › Localização › Permitir.',
    };
  }
  // code 2/3: indisponível ou demorou — quase sempre a localização/GPS desligada
  return {
    title: 'Ligue a localização do telemóvel',
    description: isApp
      ? 'Não foi possível obter a sua localização. Confirme que a LOCALIZAÇÃO (GPS) do telemóvel está LIGADA — deslize o menu de cima e toque no ícone de Localização — e registe novamente.'
      : 'Não foi possível obter a localização. Confirme que a localização do telemóvel está ligada e tente novamente.',
  };
}
