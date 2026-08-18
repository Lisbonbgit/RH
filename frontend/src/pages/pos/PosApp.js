import React, { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PosEmparelhar from './PosEmparelhar';
import PosEntrar from './PosEntrar';
import PosBloqueado from './PosBloqueado';
import {
  getDeviceToken, getLojaId, getLojaNome, getOperatorToken, getOperadorGuardado,
  guardarOperador, esquecerOperador, esquecerDispositivo,
} from '@/lib/pos';

// O shell do POS (Plano 2C, Task 1): a máquina de estados de
// docs/superpowers/plans/2026-08-15-faturacao-lacai-plano2c-ecra-pos.md —
//   1. sem token de dispositivo -> PosEmparelhar
//   2. dispositivo, sem operador -> PosEntrar (ecrã cheio)
//   3. dispositivo + operador -> a aplicação, envolta em PosBloqueado (a
//      tela de descanso aparece por cima ao fim de 5 min, sem desmontar
//      nada do que está por baixo).
// Fora daqui, /faturacao/pos (App.js) NÃO exige login do portal — os dois
// tokens do POS (dispositivo, operador) vivem só em localStorage, geridos
// por lib/pos.js, nunca no Authorization do backoffice.
//
// A caixa e a venda (Task 2 em diante do plano) ainda não existem — o que
// vai lá dentro de PosBloqueado, por agora, é só um marcador honesto.

function AppInterna({ operador, lojaNome, onSair }) {
  return (
    <div className="min-h-screen flex flex-col bg-app-grid">
      <header className="border-b bg-card">
        <div className="flex items-center justify-between gap-3 px-4 sm:px-6 h-16">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-9 w-9 rounded-lg brand-gradient flex items-center justify-center font-heading font-bold text-white shrink-0">
              L
            </div>
            <div className="leading-tight min-w-0">
              <p className="font-heading font-bold text-sm truncate">{lojaNome || 'Loja'}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 min-w-0">
            <p className="text-sm font-medium truncate max-w-[9rem] hidden sm:block">{operador?.nome}</p>
            <Button variant="ghost" size="icon" onClick={onSair} title="Trocar de operador" aria-label="Trocar de operador">
              <LogOut className="h-5 w-5" />
            </Button>
          </div>
        </div>
      </header>
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="text-muted-foreground text-center max-w-sm">
          Sessão iniciada como {operador?.nome}. A caixa e a venda são a fase seguinte deste
          ecrã — ainda por construir.
        </p>
      </div>
    </div>
  );
}

export default function PosApp() {
  const [dispositivo, setDispositivo] = useState(() => {
    const token = getDeviceToken();
    return token ? { token, lojaId: getLojaId(), lojaNome: getLojaNome() } : null;
  });
  const [operador, setOperador] = useState(() => {
    const token = getOperatorToken();
    const dados = getOperadorGuardado();
    return token && dados ? { token, dados } : null;
  });

  const dispositivoInvalido = useCallback(() => {
    esquecerDispositivo();
    setDispositivo(null);
    setOperador(null);
    toast.error('Este dispositivo já não está emparelhado. Peça um novo código ao gestor.');
  }, []);

  const sair = useCallback(() => {
    esquecerOperador();
    setOperador(null);
  }, []);

  if (!dispositivo) {
    return (
      <PosEmparelhar
        onEmparelhado={(info) => setDispositivo(info)}
      />
    );
  }

  if (!operador) {
    return (
      <PosEntrar
        onEntrar={(token, dados) => { guardarOperador(token, dados); setOperador({ token, dados }); }}
        onDispositivoInvalido={dispositivoInvalido}
        subtitulo={dispositivo.lojaNome}
      />
    );
  }

  return (
    <PosBloqueado
      onOperadorMudou={(token, dados) => setOperador({ token, dados })}
      onDispositivoInvalido={dispositivoInvalido}
    >
      <AppInterna operador={operador.dados} lojaNome={dispositivo.lojaNome} onSair={sair} />
    </PosBloqueado>
  );
}
