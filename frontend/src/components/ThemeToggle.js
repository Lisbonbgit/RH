import React, { useState } from 'react';
import { Button } from './ui/button';
import { Sun, Moon } from 'lucide-react';

/**
 * Botão claro/escuro para todo o site.
 * O tema é a classe `dark` no <html> (Tailwind darkMode: class), guardado em
 * localStorage('theme'). O arranque sem flash é feito por um script inline no
 * public/index.html; aqui só alternamos e persistimos.
 */
export default function ThemeToggle() {
  const [dark, setDark] = useState(() =>
    typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
  );

  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle('dark', next);
    try {
      localStorage.setItem('theme', next ? 'dark' : 'light');
    } catch (e) { /* modo privado sem storage: o tema fica só nesta sessão */ }
    setDark(next);
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      title={dark ? 'Mudar para tema claro' : 'Mudar para tema escuro'}
      data-testid="theme-toggle"
    >
      {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
    </Button>
  );
}
