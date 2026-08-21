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
      {/* Num painel baixo (≤900px de altura) o relógio desce a 3rem: são 24px
          que passam para o teclado do PIN, e a hora continua a ler-se do outro
          lado do balcão. O `!` é preciso porque o `md:text-7xl` é uma media
          query tão específica como esta e a ordem entre as duas não é nossa —
          aqui a altura manda sempre sobre a largura. */}
      <div className="font-heading font-bold text-6xl md:text-7xl [@media(max-height:900px)]:!text-5xl tabular-nums tracking-tight">{hora}</div>
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

// LARGURA FIXA, e teclas QUADRADAS (`aspect-square`), e as duas coisas são a
// mesma correcção — medida no browser, que é o único sítio onde este defeito
// existe.
//
// O que cá estava era `w-full max-w-[19rem]` com teclas `h-16`, e a conta que
// isso parece fazer (304px de grelha, teclas de 93×64) nunca chegou a
// acontecer: o `w-full` é uma PERCENTAGEM, e o pai (`flex flex-col
// items-center`, dentro de outro `items-center`) não tem largura própria —
// encolhe ao conteúdo. A largura da grelha passava a ser decidida pelo irmão
// mais largo, que é o link "Escolher outra pessoa": 158,2px. Tirando os dois
// intervalos de 12px, cada tecla ficava com **44,7px de largura para 64px de
// altura** — mais alta do que larga, espremida, e o `max-w-[19rem]` nunca
// chegava a morder. É este o "esticado" que o dono viu, e é por isso que ele
// mudava de forma consoante o texto à volta.
//
// Uma largura em `rem` não depende de ninguém: 17,5rem = 280px, três teclas
// de 85,3px quadradas, que é a escala a que este ecrã se toca — um dedo, com
// um cliente à frente. (O avatar DESTE ecrã, o da pessoa já escolhida, mede
// `h-16` = 64px; os 80px do `h-20 w-20` são os do ecrã ANTERIOR, o de
// escolher a cara. Quem vier ajustar esta escala compara com 64, não com 80.)
// O tecto é em `vw` e não em `%` de propósito: é uma medida absoluta, e uma
// percentagem aqui era voltar a pendurar a grelha na largura que o pai não
// tem.
//
// O SEGUNDO TECTO É A ALTURA, e é a outra metade da mesma correcção: teclas
// de 85,3px fazem uma grelha de 4×85,3 + 3×12 = 377px, e isso deixou de
// caber no painel de um balcão. Medido no browser, com subtítulo (os dois
// estados desta tela levam um): a 1366×768 e a 1024×768 o `0` acabava 17,3px
// ABAIXO da dobra, com 41px de overflow; a 1280×720 viam-se 20 dos 85,3px do
// `0`; a 1366×640 — o que sobra de um painel 768 quando o POS não corre em
// quiosque — o `0` e o apagar não se viam de todo e o 7/8/9 ficava cortado a
// meio. Uma operadora sem o zero não entra no sistema.
//
// Por isso a largura é o MENOR de três tectos (e nunca menos do que um chão):
//   · 17,5rem — o tamanho de dedo, quando há altura para ele;
//   · 100vw − 3rem — o ecrã menos o `p-6` do pai;
//   · 75vh − 256px — a altura que sobra, convertida em largura.
// O terceiro é a conta da grelha ao contrário: com `k` = lado da tecla, a
// grelha mede 4k + 36 de alto e 3k + 24 de largo, logo
// largura = ¾·(altura disponível − 36) + 24. O resto deste ecrã ocupa ~335px
// CONSTANTES abaixo dos 900px de altura (é para isso que servem as trocas de
// `gap`/`padding`/tamanho do relógio lá em baixo, e é por isso que a linha de
// erro do PIN está sempre reservada em vez de aparecer só quando falha — se
// aparecesse, empurrava o teclado 32px para fora outra vez, exactamente na
// vez em que é preciso reescrever o PIN). ¾·335 + 3 ≈ 254; os 256 são esses
// com uma folga pequena — medido a 1366×640, o ecrã inteiro dá 637,3px em
// 640. O chão de 13,5rem são teclas de 64px, o tamanho antigo: abaixo de
// ~630px de altura o ecrã prefere deslizar a encolher a tecla mais do que
// isso (a 1366×560 mede-se: teclas de 64px e 64px de deslize).
//
// O compromisso, por extenso: a 768 e a 720 a tecla continua nos 85,3px
// inteiros; só a 640 é que encolhe (~67px, ainda maior do que os 64px de
// antes) para o teclado TODO caber. Uma tecla um pouco mais pequena toca-se;
// uma tecla fora do ecrã não.
function TeclasNumericas({ onDigito, onApagar, desativado }) {
  const teclas = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'apagar'];
  return (
    <div className="grid grid-cols-3 gap-3 w-[max(13.5rem,min(17.5rem,100vw_-_3rem,75vh_-_256px))]">
      {teclas.map((t, i) => {
        if (t === '') return <div key={i} />;
        if (t === 'apagar') {
          return (
            <button
              key={i}
              type="button"
              disabled={desativado}
              onClick={onApagar}
              className="aspect-square rounded-2xl border bg-card flex items-center justify-center active:scale-[0.96] transition-transform disabled:opacity-50 hover:bg-accent"
              aria-label="Apagar"
            >
              <Delete className="h-7 w-7" />
            </button>
          );
        }
        return (
          <button
            key={i}
            type="button"
            disabled={desativado}
            onClick={() => onDigito(t)}
            className="aspect-square rounded-2xl border bg-card text-3xl font-heading font-bold active:scale-[0.96] transition-transform disabled:opacity-50 hover:bg-accent"
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
        const { data } = await entrarComPin(selecionado.id, pin);
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
        // 401 "PIN incorrecto." — a mesma resposta quer o PIN esteja errado,
        // quer a pessoa tenha sido desactivada ou mudada de loja entretanto
        // (o servidor não os distingue de propósito). Nunca deixa entrar; a
        // mensagem já vem certa de lá.
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
      <div className="flex flex-col items-center gap-6 [@media(max-height:900px)]:gap-3">
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

        {/* A linha do erro está SEMPRE aqui, vazia ou não (`min-h-5`): se
            aparecesse só quando o PIN falha, empurrava o teclado 32px para
            baixo — e num painel baixo isso é o `0` a sair do ecrã na única
            vez em que é mesmo preciso reescrever o PIN. */}
        <p className="text-destructive text-sm font-medium text-center max-w-xs min-h-5" aria-live="polite">{erroPin}</p>

        <TeclasNumericas onDigito={digitar} onApagar={apagar} desativado={enviando} />
      </div>
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [carregando, erroLista, selecionado, operadores, pin, enviando, erroPin]);

  // O ecrã INTEIRO é o orçamento de altura do teclado do PIN — cada px que
  // este cabeçalho gasta é um px que a tecla não tem. Por isso, num painel de
  // ≤900px de altura (todos os do balcão: 768, 720, e os 640 que sobram de um
  // 768 com barra de browser), os espaços encolhem: `gap-10`→`gap-4` entre o
  // relógio e o conteúdo, `p-6`→`py-2` em cima e em baixo. Acima disso — um
  // monitor a sério — fica tudo como estava, que é onde há espaço para
  // respirar. O relógio e o subtítulo passaram a viver no MESMO bloco: o
  // `-mt-8` que o subtítulo tinha era um `gap-10` a ser desfeito à mão, e
  // desfazia-o com um número que deixava de bater assim que o `gap` mudasse.
  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center gap-10 [@media(max-height:900px)]:gap-4 p-6 [@media(max-height:900px)]:py-2 bg-app-grid">
      <div className="flex flex-col items-center">
        <Relogio />
        {subtitulo && <p className="text-muted-foreground mt-1 text-center">{subtitulo}</p>}
      </div>
      {conteudo}
    </div>
  );
}
