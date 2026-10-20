import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ScanFace } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '@/contexts/AuthContext';
import { emailGuardado, temFaceId, verificar } from '@/lib/faceid';
import {
  abrirBarreira, barreiraFechada, esquecerRecusa, fecharBarreira, outraContaTemDeSair, voltouATempo,
} from '@/lib/sessao';

// **A barreira do Face ID** — o ecrã opaco por cima do bolso ao abrir a app e ao
// voltar depois de mais de 5 minutos fora. Só existe na casca com Face ID
// ligado; no browser e na build 2 desenha os filhos e mais nada.
//
// Os filhos ficam MONTADOS por baixo: quem estava a marcar uma ida e foi ver o
// WhatsApp não perde o que escreveu. Os números não aparecem porque a barreira
// é um <dialog> modal (camada de cima do browser, por cima até das janelas do
// Radix), e não se pedem porque o `lib/bolso.js` espera por ela
// (`esperarBarreira`). Ver a memória «Barreira de ecrã = dialog modal».
//
// Fecha LOGO ao esconder (a miniatura do selector de apps não pode mostrar
// números). Face ID falhado ou cancelado → `logout()` (o Keychain fica) e o
// `ProtectedRoute` leva ao login com `state.from`. Interrompido pelo sistema
// (`null`) → fica fechada, com o botão. Sem Face ID possível → `logout()`: a
// barreira nunca abre sem um rosto (ou sem ter voltado dentro dos 5 minutos).
//
// Só fecha para a dona do Face ID (`fecharBarreira` diz `false` para a sessão de
// outra conta — decisão A do dono). Essa, ao voltar depois de 5 minutos, vai para
// a senha: `outraContaTemDeSair()`.
//
// Mora DENTRO do `ProtectedRoute`: o «Sem ligação — tentar de novo» aparece no
// lugar dela (sem user não há Barreira montada), nunca por baixo da cortina.
export default function Barreira({ children }) {
  const { logout } = useAuth();
  const [fechada, setFechada] = useState(barreiraFechada);

  const abrir = useCallback(() => { abrirBarreira(); setFechada(false); }, []);
  const entrar = useCallback(async () => {
    const r = await verificar();
    if (r === true) abrir();
    else if (r === false) logout();
  }, [abrir, logout]);

  // Voltou dentro dos 5 minutos → abre sem rosto. Senão, o rosto. Sem Face ID
  // possível (bloqueado depois de rostos errados — noutra app, até —, rosto
  // apagado, licença retirada) não há como verificar ninguém: login, como num
  // rosto falhado (desenho §5.2 e §5.3, decisão 2A). O Keychain fica.
  const decidir = useCallback(async () => {
    if (!barreiraFechada()) return;
    if (voltouATempo()) abrir();
    else if (await temFaceId()) entrar();
    else logout();
  }, [abrir, entrar, logout]);

  useEffect(() => {
    decidir();
    const aoMudar = () => {
      if (document.hidden) {
        if (fecharBarreira()) setFechada(true);
      } else if (outraContaTemDeSair()) {
        logout();
      } else {
        decidir();
      }
    };
    document.addEventListener('visibilitychange', aoMudar);
    return () => document.removeEventListener('visibilitychange', aoMudar);
  }, [decidir, logout]);

  return (
    <>
      {children}
      {fechada && <Cortina email={emailGuardado()} onEntrar={entrar} />}
    </>
  );
}

function Cortina({ email, onEntrar }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    // `pointer-events-auto`: com uma janela do Radix aberta por baixo, o body
    // fica com `pointer-events:none` e a barreira herdava-o. O `stopPropagation`
    // impede o toque de chegar ao `document`, onde o Radix fecharia a janela.
    <dialog
      ref={ref}
      aria-label="Entrar com Face ID"
      onCancel={(e) => e.preventDefault()}
      onPointerDown={(e) => e.stopPropagation()}
      className="pointer-events-auto fixed inset-0 m-0 h-[100dvh] max-h-none w-screen max-w-none
                 bg-background p-0 text-foreground backdrop:bg-background"
    >
      <div className="flex h-full flex-col items-center justify-center gap-6 px-6 safe-area-inset-top">
        <ScanFace className="h-14 w-14 text-muted-foreground" aria-hidden="true" />
        <p className="text-center text-[15px] font-semibold">Gestão Lisbonb</p>
        <button
          type="button"
          onClick={onEntrar}
          className="h-12 w-full max-w-xs rounded-2xl bg-primary px-4 text-[15px] font-semibold
                     text-primary-foreground dark:text-background focus-visible:outline-none
                     focus-visible:ring-2 focus-visible:ring-ring"
        >
          Entrar como {email}
        </button>
      </div>
    </dialog>
  );
}

// O item «Usar Face ID» do menu lateral, para quem disse «Agora não» e mudou de
// ideias (ou trocou de conta neste telemóvel). Para guardar a senha é preciso
// escrevê-la: esquece-se o «não», termina-se a sessão (sem tocar no Keychain) e
// o login, depois da senha, pergunta outra vez. A `className` vem do menu, para
// ficar igual aos outros itens (o ícone também).
export function UsarFaceId({ className = '' }) {
  const { user, logout } = useAuth();
  const [mostrar, setMostrar] = useState(false);
  useEffect(() => {
    let vivo = true;
    temFaceId().then((tem) => {
      if (vivo) setMostrar(tem && !!user?.email && emailGuardado() !== user.email);
    });
    return () => { vivo = false; };
  }, [user]);
  if (!mostrar) return null;
  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        esquecerRecusa(user.email);
        toast('Entre com a senha para ligar o Face ID.');
        logout();
      }}
    >
      <ScanFace className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
      Usar Face ID
    </button>
  );
}
