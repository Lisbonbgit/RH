import { Capacitor } from '@capacitor/core';

// Sincroniza a barra de estado nativa (Android/iOS) com o tema da app.
// O tema é a classe `dark` no <html> (ver ThemeToggle). Aqui garantimos que a
// cor de fundo e o estilo dos ícones da barra acompanham o tema, e — combinado
// com o opt-out de edge-to-edge no tema nativo (android/values/styles.xml) — que
// o conteúdo não fica por baixo da barra de estado.

const LIGHT_BG = '#ffffff';
const DARK_BG = '#0b1120';

let started = false;

async function apply() {
  if (!Capacitor.isNativePlatform()) return;
  try {
    const { StatusBar, Style } = await import('@capacitor/status-bar');
    const isDark = document.documentElement.classList.contains('dark');
    // Style.Dark = fundo escuro (ícones claros); Style.Light = fundo claro (ícones escuros).
    await StatusBar.setStyle({ style: isDark ? Style.Dark : Style.Light });
    if (Capacitor.getPlatform() === 'android') {
      await StatusBar.setBackgroundColor({ color: isDark ? DARK_BG : LIGHT_BG });
    }
  } catch (e) {
    /* plugin indisponível (ex.: web): ignora */
  }
}

export function initNativeStatusBar() {
  if (started || typeof document === 'undefined') return;
  started = true;
  apply();
  // Re-sincroniza sempre que a classe `dark` do <html> muda (toggle de tema).
  try {
    const obs = new MutationObserver(apply);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
  } catch (e) {
    /* sem MutationObserver: aplica só uma vez */
  }
}
