import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Delete, Loader2, ChevronLeft, AlertCircle } from 'lucide-react';
import { getOperadoresDoDispositivo, entrarComPin, detalhesErroPos, MSG_DISPOSITIVO_INVALIDO } from '@/lib/pos';

// O MESMO ecrã serve dois estados da máquina de PosApp: a entrada (estado 2,
// sem operador ainda) e a tela de descanso (estado 3, 5 minutos sem toques —
// ver PosBloqueado.js, que renderiza este componente dentro de um overlay
// fixo, por cima da app, sem desmontar nada por baixo). É por isto que este
// ficheiro é puramente presentacional em relação ao SEU contentor: enche o
// espaço que lhe derem (h-full/w-full), nunca assume que é a página inteira —
// quem decide isso é o pai (PosApp para o ecrã cheio, PosBloqueado para o
// overlay).
const iniciais = (nome) =>
  (nome || '?').split(' ').filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase();

function Relogio() {
  const [agora, setAgora] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setAgora(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const hora = agora.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
  const data = agora.toLocaleDateString('pt-PT', { weekday: 'long', day: 'numeric', month: 'long' });
  return (
    <div className="text-center select-none">
      <div className="font-heading font-bold text-6xl md:text-7xl tabular-nums tracking-tight">{hora}</div>
      <div className="text-muted-foreground mt-1 capitalize">{data}</div>
    </div>
  );
}

function CaraOperador({ operador, onEscolher }) {
  return (
    <button
      type="button"
      onClick={() => onEscolher(operador)}
      className="flex flex-col items-center gap-3 p-3 rounded-2xl transition-colors hover:bg-accent active:scale-[0.97] transition-transform"
    >
      {operador.foto ? (
        <img
          src={operador.foto}
          alt={operador.nome}
          className="h-20 w-20 md:h-24 md:w-24 rounded-full object-cover shadow-md shrink-0"
        />
      ) : (
        <div className="h-20 w-20 md:h-24 md:w-24 rounded-full brand-gradient text-white flex items-center justify-center text-2xl font-heading font-bold shadow-md shrink-0">
          {iniciais(operador.nome)}
        </div>
      )}
      <span className="font-medium text-sm md:text-base max-w-[9rem] truncate">{operador.nome}</span>
    </button>
  );
}

function TeclasNumericas({ onDigito, onApagar, desativado }) {
  const teclas = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'apagar'];
  return (
    <div className="grid grid-cols-3 gap-3 w-full max-w-[19rem]">
      {teclas.map((t, i) => {
        if (t === '') return <div key={i} />;
        if (t === 'apagar') {
          return (
            <button
              key={i}
              type="button"
              disabled={desativado}
              onClick={onApagar}
              className="h-16 rounded-2xl border bg-card flex items-center justify-center active:scale-[0.96] transition-transform disabled:opacity-50"
              aria-label="Apagar"
            >
              <Delete className="h-6 w-6" />
            </button>
          );
        }
        return (
          <button
            key={i}
            type="button"
            disabled={desativado}
            onClick={() => onDigito(t)}
            className="h-16 rounded-2xl border bg-card text-2xl font-heading font-bold active:scale-[0.96] transition-transform disabled:opacity-50 hover:bg-accent"
          >
            {t}
          </button>
        );
      })}
    </div>
  );
}

export default function PosEntrar({ onEntrar, onDispositivoInvalido, subtitulo }) {
  const [operadores, setOperadores] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erroLista, setErroLista] = useState(null);
  const [selecionado, setSelecionado] = useState(null);
  const [pin, setPin] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erroPin, setErroPin] = useState(null);

  const carregarOperadores = useCallback(async () => {
    setCarregando(true);
    setErroLista(null);
    try {
      const { data } = await getOperadoresDoDispositivo();
      setOperadores(data || []);
    } catch (error) {
      if (error.response?.status === 401 && onDispositivoInvalido) {
        onDispositivoInvalido();
        return;
      }
      setErroLista(detalhesErroPos(error, 'Não foi possível obter a lista de operadores.').mensagem);
    } finally {
      setCarregando(false);
    }
  }, [onDispositivoInvalido]);

  useEffect(() => { carregarOperadores(); }, [carregarOperadores]);

  const escolher = (operador) => {
    setSelecionado(operador);
    setPin('');
    setErroPin(null);
  };

  const voltar = () => {
    setSelecionado(null);
    setPin('');
    setErroPin(null);
  };

  const digitar = (d) => {
    if (enviando) return;
    setErroPin(null);
    setPin((atual) => (atual.length >= 4 ? atual : atual + d));
  };

  const apagar = () => {
    if (enviando) return;
    setErroPin(null);
    setPin((atual) => atual.slice(0, -1));
  };

  // PIN sempre como STRING — "0007" nunca pode virar 7. Submete sozinho ao
  // 4º dígito (é o próprio teclado grande que substitui o Enter).
  useEffect(() => {
    if (pin.length !== 4 || enviando || !selecionado) return;
    let cancelado = false;
    (async () => {
      setEnviando(true);
      try {
        const { data } = await entrarComPin(pin);
        if (cancelado) return;
        onEntrar(data.operator_token, data.operador);
      } catch (error) {
        if (cancelado) return;
        // /pos/entrar depende do dispositivo E do PIN: um 401 pode ser
        // qualquer um dos dois — só a mensagem exacta os distingue (o
        // dispositivo foi revogado pelo gestor a meio do turno, por
        // exemplo). Nesse caso volta ao emparelhamento; nunca finge que foi
        // só um PIN errado.
        if (error.response?.status === 401 && error.response?.data?.detail === MSG_DISPOSITIVO_INVALIDO && onDispositivoInvalido) {
          onDispositivoInvalido();
          return;
        }
        // 401 "PIN incorrecto." ou 409 "PIN em conflito, contacte o gestor."
        // — os dois nunca deixam entrar; a mensagem já vem certa do servidor.
        const { mensagem } = detalhesErroPos(error, 'Não foi possível entrar.');
        setErroPin(mensagem);
        setPin('');
      } finally {
        if (!cancelado) setEnviando(false);
      }
    })();
    return () => { cancelado = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pin]);

  const conteudo = useMemo(() => {
    if (carregando) {
      return (
        <div className="flex items-center justify-center py-16 text-muted-foreground gap-2">
          <Loader2 className="h-5 w-5 animate-spin" /> A carregar operadores…
        </div>
      );
    }
    if (erroLista) {
      return (
        <div className="flex flex-col items-center gap-3 py-16 text-center max-w-sm">
          <AlertCircle className="h-8 w-8 text-destructive" />
          <p className="text-muted-foreground">{erroLista}</p>
          <button
            type="button"
            onClick={carregarOperadores}
            className="text-primary font-medium underline underline-offset-4"
          >
            Tentar novamente
          </button>
        </div>
      );
    }
    if (!selecionado) {
      if (operadores.length === 0) {
        return (
          <p className="text-muted-foreground py-16 text-center max-w-sm">
            Não há operadores disponíveis para esta loja. Contacte o gestor.
          </p>
        );
      }
      return (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2 sm:gap-4 max-w-3xl">
          {operadores.map((op) => (
            <CaraOperador key={op.id} operador={op} onEscolher={escolher} />
          ))}
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center gap-6">
        <button
          type="button"
          onClick={voltar}
          disabled={enviando}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground self-start disabled:opacity-50"
        >
          <ChevronLeft className="h-4 w-4" /> Escolher outra pessoa
        </button>

        {selecionado.foto ? (
          <img src={selecionado.foto} alt={selecionado.nome} className="h-16 w-16 rounded-full object-cover shadow-md" />
        ) : (
          <div className="h-16 w-16 rounded-full brand-gradient text-white flex items-center justify-center text-xl font-heading font-bold shadow-md">
            {iniciais(selecionado.nome)}
          </div>
        )}
        <p className="font-heading font-bold text-lg -mt-3">{selecionado.nome}</p>

        <div className="flex items-center gap-3" aria-live="polite">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className={`h-4 w-4 rounded-full border-2 ${i < pin.length ? 'bg-primary border-primary' : 'border-muted-foreground/40'}`}
            />
          ))}
          {enviando && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground ml-2" />}
        </div>

        {erroPin && <p className="text-destructive text-sm font-medium text-center max-w-xs">{erroPin}</p>}

        <TeclasNumericas onDigito={digitar} onApagar={apagar} desativado={enviando} />
      </div>
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [carregando, erroLista, selecionado, operadores, pin, enviando, erroPin]);

  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center gap-10 p-6 bg-app-grid">
      <Relogio />
      {subtitulo && <p className="text-muted-foreground -mt-8">{subtitulo}</p>}
      {conteudo}
    </div>
  );
}
