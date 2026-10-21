import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarDays, Menu, Receipt, X } from 'lucide-react';
import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useAuth } from '@/contexts/AuthContext';
import { semanasDoMes, tituloDoDia } from '@/lib/calendario';
import { UsarFaceId } from './Barreira';

// O que os ecrãs da Gestão Lisbonb (`/bolso` e `/bolso/calendario`) partilham: o manifesto,
// a memória do `localStorage`, o segmento das calhas, o menu lateral e a grelha do mês.

// O `localStorage` pode não existir ou rebentar (modo privado, dados bloqueados): lê-se e
// grava-se sempre dentro de try/catch, e o ecrã funciona sem ele.
export const ler = (chave, omissao) => {
  try { return localStorage.getItem(chave) ?? omissao; } catch (e) { return omissao; }
};
export const guardar = (chave, valor) => {
  try {
    if (valor === null) localStorage.removeItem(chave);
    else localStorage.setItem(chave, valor);
  } catch (e) { /* modo privado */ }
};

// O manifesto do portal aponta para o POS (`start_url: /faturacao/pos`). Sem esta troca,
// "Adicionar ao Ecrã Principal" a partir daqui instalava um ícone que **abre o balcão da
// loja** — o manifesto é que manda, não o endereço que está à frente.
export function useManifestoDoBolso() {
  useEffect(() => {
    const link = document.querySelector('link[rel="manifest"]');
    const anterior = link ? link.getAttribute('href') : null;
    if (link) link.setAttribute('href', '/bolso-manifest.json');

    // O iPhone ignora o `icons` do manifesto e usa o `apple-touch-icon`.
    const apple = document.createElement('link');
    apple.rel = 'apple-touch-icon';
    apple.href = '/icones/bolso-180.png';
    document.head.appendChild(apple);

    const titulo = document.title;
    document.title = 'Gestão Lisbonb';
    return () => {
      if (link && anterior) link.setAttribute('href', anterior);
      apple.remove();
      document.title = titulo;
    };
  }, []);
}

// A calha dos segmentos: `h-12` com `p-0.5` deixa cada segmento com 44px — o mínimo do iOS,
// medido no ecrã. Com `h-11 p-[3px]` ficavam em 38 e nenhum teste apanhava isso.
export function Calha({ children }) {
  return <div className="flex bg-muted rounded-xl p-0.5 h-12">{children}</div>;
}

// Uma só língua de selecção: `bg-primary` com o texto do portal — excepto no tema escuro,
// onde o `--primary` é um azul claro e branco por cima dá 3,4:1; aí o texto passa a ser o
// fundo da página (5,6:1, medido). O que NÃO está escolhido fica em `text-foreground`: sobre
// `bg-muted` no escuro o `text-muted-foreground` dava 3,4:1.
export function Segmento({ activo, onClick, children }) {
  return (
    <button
      type="button" onClick={onClick} aria-pressed={activo}
      className={`flex-1 min-w-0 h-full rounded-lg px-1 text-[13px] font-semibold truncate
                  transition-colors duration-150
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${
        activo ? 'bg-primary text-primary-foreground dark:text-background' : 'text-foreground'
      }`}
    >
      {children}
    </button>
  );
}

// As secções da app. O teste `test_ecra_do_calendario.py` confronta cada caminho com o
// `App.js`: um destino sem rota abria um ecrã em branco sem nada partir.
export const DESTINOS = [
  { caminho: '/bolso', rotulo: 'Faturação', Icone: Receipt },
  { caminho: '/bolso/calendario', rotulo: 'Calendário', Icone: CalendarDays },
];

export function BotaoMenu({ onClick }) {
  return (
    <button
      type="button" onClick={onClick} aria-label="Abrir menu"
      className="h-11 w-11 shrink-0 inline-flex items-center justify-center rounded-lg active:bg-accent/60
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Menu className="h-5 w-5" />
    </button>
  );
}

// O menu lateral (☰). O `SheetContent` não desenha o fecho de 16px (`hideClose`): o daqui
// tem 44px, e o conteúdo respeita a zona da notch (a casca pinta até às bordas).
export function MenuLateral({ aberto, onFechar, actual }) {
  const navigate = useNavigate();
  const { terminarSessao, user } = useAuth();
  const ir = (caminho) => {
    onFechar();
    if (caminho !== actual) navigate(caminho);
  };
  return (
    <Sheet open={aberto} onOpenChange={(v) => { if (!v) onFechar(); }}>
      <SheetContent side="left" hideClose aria-describedby={undefined} className="p-0 w-[80%] max-w-xs">
        <div className="flex h-full flex-col safe-area-inset-top safe-area-inset-bottom">
          <div className="flex items-center gap-2 pl-4 pr-1 h-14 border-b shrink-0">
            <SheetTitle className="flex-1 min-w-0 truncate text-base">Gestão Lisbonb</SheetTitle>
            <SheetClose
              aria-label="Fechar menu"
              className="h-11 w-11 inline-flex items-center justify-center rounded-lg
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-5 w-5" />
            </SheetClose>
          </div>
          <nav className="flex-1 py-2">
            {DESTINOS.map(({ caminho, rotulo, Icone }) => (
              <button
                key={caminho} type="button" onClick={() => ir(caminho)}
                aria-current={caminho === actual ? 'page' : undefined}
                className={`w-full h-12 px-4 flex items-center gap-3 text-left text-[15px] font-semibold
                            active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2
                            focus-visible:ring-ring focus-visible:ring-inset ${caminho === actual ? 'bg-accent' : ''}`}
              >
                <Icone className="h-5 w-5 text-muted-foreground" />
                {rotulo}
              </button>
            ))}
            <UsarFaceId
              className="w-full h-12 px-4 flex items-center gap-3 text-left text-[15px] font-semibold
                         active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-ring focus-visible:ring-inset"
            />
          </nav>
          {/* Sair é raro e irreversível: fica no fundo, e sem vermelho (no bolso o vermelho
              quer dizer outra coisa — faturação a descer, buraco por tapar). */}
          <button
            type="button" onClick={() => { onFechar(); terminarSessao(); }}
            className="h-14 shrink-0 border-t px-4 flex items-center justify-between gap-3 text-left
                       active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="text-[13px] text-muted-foreground truncate">{user?.name || ''}</span>
            <span className="text-[15px] font-semibold shrink-0">Terminar sessão</span>
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

const LETRAS = ['S', 'T', 'Q', 'Q', 'S', 'S', 'D'];

// A grelha do mês, própria (não o `ui/calendar.jsx`: o react-day-picker 8 declara o date-fns
// 2/3 e o instalado é o 4). Dias de 44px; feriados noutra cor; `pontos` com a cor do filtro.
// Serve o ecrã (um dia escolhido) e o painel da ida (vários).
export function GrelhaDoMes({
  ano, mes, hoje, escolhidos = [], onTocar, pontos = [], corDoPonto = 'bg-destructive', feriados = [],
}) {
  return (
    <div>
      <div className="grid grid-cols-7 pb-1 text-center text-[11px] font-semibold text-muted-foreground" aria-hidden="true">
        {LETRAS.map((letra, i) => <span key={i}>{letra}</span>)}
      </div>
      {semanasDoMes(ano, mes).map((semana) => (
        <div key={semana.find(Boolean)} className="grid grid-cols-7 gap-0.5">
          {semana.map((iso, i) => {
            if (!iso) return <span key={`vazio-${i}`} />;
            const escolhido = escolhidos.includes(iso);
            const feriado = feriados.includes(iso);
            const ponto = pontos.includes(iso);
            return (
              <button
                key={iso} type="button" data-dia={iso} aria-pressed={escolhido} onClick={() => onTocar(iso)}
                aria-label={`${tituloDoDia(iso)}${feriado ? ', feriado' : ''}${ponto ? ', com marcação' : ''}`}
                className={`relative h-11 w-full rounded-lg text-[15px] tabular-nums transition-colors duration-150
                            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  escolhido ? 'bg-primary text-primary-foreground dark:text-background font-bold'
                    : feriado ? 'text-warning-strong font-semibold' : 'text-foreground'
                } ${iso === hoje && !escolhido ? 'ring-1 ring-inset ring-primary font-bold' : ''}`}
              >
                {Number(iso.slice(8))}
                {ponto && (
                  <span
                    data-ponto="" aria-hidden="true"
                    className={`absolute bottom-1 left-1/2 h-1.5 w-1.5 -translate-x-1/2 rounded-full ${
                      escolhido ? 'bg-current' : corDoPonto}`}
                  />
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
