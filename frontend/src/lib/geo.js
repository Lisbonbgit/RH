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
async function getNativePosition() {
  try {
    let perm = await Geolocation.checkPermissions();
    if (perm.location !== 'granted') {
      perm = await Geolocation.requestPermissions();
      if (perm.location !== 'granted') {
        return { position: null, errorCode: 1 }; // permissão negada
      }
    }
    const pos = await Geolocation.getCurrentPosition({ enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 });
    return {
      position: { latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy },
      errorCode: null,
    };
  } catch (e) {
    const msg = String((e && e.message) || '').toLowerCase();
    const code = msg.includes('denied') || msg.includes('permission') ? 1 : msg.includes('timeout') ? 3 : 2;
    return { position: null, errorCode: code };
  }
}

// ---------- API pública ----------
export async function getCurrentPositionSmart() {
  return Capacitor.isNativePlatform() ? getNativePosition() : getWebPosition();
}

// Mensagem de ajuda consoante o motivo da falha (adapta-se a app/web).
export function geoHelpMessage(code) {
  const isApp = Capacitor.isNativePlatform();
  if (code === 1) {
    return {
      title: 'Localização sem permissão',
      description: isApp
        ? 'Ative a localização para a app Lisbonb RH: Definições › Lisbonb RH › Localização › "Ao usar a app". Depois registe novamente.'
        : 'No iPhone: Definições › Privacidade e Segurança › Serviços de Localização (ligado) e, em Safari, "Ao usar a app". Depois, na barra toque em "AA" › Definições do Website › Localização › Permitir.',
    };
  }
  if (code === 3) {
    return {
      title: 'A localização demorou demasiado',
      description: 'Sinal fraco. Confirme que a localização está ligada e tente outra vez, de preferência junto a uma janela ou no exterior.',
    };
  }
  return {
    title: 'Não foi possível obter a localização',
    description: 'Este local exige localização para registar o ponto. Ative a localização e permita o acesso à app.',
  };
}
