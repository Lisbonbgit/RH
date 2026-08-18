import React, { useEffect, useRef, useState } from 'react';
import PosEntrar from './PosEntrar';
import { guardarOperador } from '@/lib/pos';

const CINCO_MINUTOS_MS = 5 * 60 * 1000;
const INTERVALO_VERIFICACAO_MS = 10 * 1000;
// Qualquer um destes é "a funcionária está a mexer no ecrã" — não só toques:
// um PC de balcão também tem rato e teclado (ver Global Constraints do
// plano). mousemove entra na lista mas só actualiza uma ref, nunca um
// state — senão cada pixel de movimento do rato pedia um novo render.
const EVENTOS_DE_ATIVIDADE = ['pointerdown', 'keydown', 'touchstart', 'wheel', 'mousemove'];

// Envolve a app já com operador (Task 2 em diante) e, ao fim de 5 minutos
// sem toques, SOBREPÕE a mesma tela de entrada — sem desmontar `children`.
// A venda em curso (quando existir, Task 3) fica exactamente como estava:
// só um `div` novo aparece por cima, nunca troca a árvore de baixo.
export default function PosBloqueado({ children, onOperadorMudou, onDispositivoInvalido }) {
  const [bloqueado, setBloqueado] = useState(false);
  const ultimaAtividade = useRef(Date.now());

  useEffect(() => {
    const marcar = () => { ultimaAtividade.current = Date.now(); };
    EVENTOS_DE_ATIVIDADE.forEach((ev) => document.addEventListener(ev, marcar, { passive: true }));
    const intervalo = setInterval(() => {
      if (!bloqueado && Date.now() - ultimaAtividade.current >= CINCO_MINUTOS_MS) {
        setBloqueado(true);
      }
    }, INTERVALO_VERIFICACAO_MS);
    return () => {
      EVENTOS_DE_ATIVIDADE.forEach((ev) => document.removeEventListener(ev, marcar));
      clearInterval(intervalo);
    };
  }, [bloqueado]);

  const desbloquear = (operatorToken, operador) => {
    // "Volta-se com a cara e o PIN" (spec) — quem desbloqueia pode ser
    // outra pessoa a assumir o balcão, não necessariamente quem estava lá
    // antes; o token/operador guardados passam a ser os desta entrada, tal
    // como aconteceria com um login novo.
    guardarOperador(operatorToken, operador);
    ultimaAtividade.current = Date.now();
    setBloqueado(false);
    if (onOperadorMudou) onOperadorMudou(operatorToken, operador);
  };

  return (
    <>
      {children}
      {bloqueado && (
        <div className="fixed inset-0 z-50 bg-background/98 backdrop-blur-sm animate-fade-in overflow-y-auto">
          <PosEntrar
            onEntrar={desbloquear}
            onDispositivoInvalido={onDispositivoInvalido}
            subtitulo="Sessão em pausa — toque na sua cara para continuar"
          />
        </div>
      )}
    </>
  );
}
