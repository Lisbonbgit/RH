import React, { useEffect, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useAuth } from '@/contexts/AuthContext';
import { getHistorico } from '@/lib/bolso';
import { MESES, linhaDoHistorico, mensagemDeErro } from '@/lib/calendario';

// O histórico do calendário (desenho das trocas, §2 e §3): quem mudou o quê no mês do dia
// escolhido, da mudança mais recente para a mais antiga (a ordem é a do servidor). Só se monta
// ao abrir, e é aí que faz o pedido: abrir o ecrã continua a ser um pedido só.
export default function PainelHistorico({ ano, mes, onFechar }) {
  const { logout } = useAuth();
  const [entradas, setEntradas] = useState(null);
  const [erro, setErro] = useState(null);

  // 401: o `lib/bolso.js` já tentou a re-entrada pelo Face ID → só `logout()`, como o resto do ecrã.
  useEffect(() => {
    let vivo = true;
    getHistorico(ano, mes)
      .then(({ data }) => { if (vivo) setEntradas(data.entradas || []); })
      .catch((e) => {
        if (e?.response?.status === 401) { logout(); return; }
        if (vivo) setErro(mensagemDeErro(e));
      });
    return () => { vivo = false; };
  }, [ano, mes, logout]);

  return (
    <Sheet open onOpenChange={(aberto) => { if (!aberto) onFechar(); }}>
      <SheetContent
        side="bottom" hideClose aria-describedby={undefined}
        className="p-0 gap-0 rounded-t-2xl max-h-[92dvh] flex flex-col"
      >
        <div className="flex items-center gap-2 pl-4 pr-1 h-14 border-b shrink-0">
          <SheetTitle className="min-w-0 flex-1 text-base truncate">Histórico de {MESES[mes - 1]}</SheetTitle>
          <SheetClose
            aria-label="Fechar"
            className="h-11 w-11 inline-flex items-center justify-center rounded-lg
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-5 w-5" />
          </SheetClose>
        </div>

        <div className="overflow-y-auto px-4 pt-3 pb-4 safe-area-inset-bottom">
          {erro ? (
            <p role="alert" className="text-[14px] text-destructive-strong dark:text-destructive whitespace-pre-line break-words">{erro}</p>
          ) : !entradas ? (
            <p role="status" className="my-4 flex items-center justify-center gap-2 text-[14px] text-muted-foreground">
              <Loader2 aria-hidden="true" className="h-5 w-5 animate-spin" />A ler
            </p>
          ) : entradas.length === 0 ? (
            <p className="text-[14px] text-muted-foreground">
              Sem alterações registadas neste mês. As mudanças só ficam registadas desde que o histórico existe.
            </p>
          ) : (
            <ul className="divide-y">
              {entradas.map((e) => (
                <li key={e.id} className="py-2 text-[14px] break-words">{linhaDoHistorico(e)}</li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
