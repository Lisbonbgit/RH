import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, AlertCircle, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import useTituloDoPos from './useTituloDoPos';
import PosEmparelhar from './PosEmparelhar';
import PosEntrar from './PosEntrar';
import PosBloqueado from './PosBloqueado';
import PosCaixaFechada from './PosCaixaFechada';
import PosMenuCaixa from './PosMenuCaixa';
import PosFecharCaixa from './PosFecharCaixa';
import PosVenda from './PosVenda';
import PosFaixaModo from './PosFaixaModo';
import {
  getDeviceToken, getLojaId, getLojaNome, getOperatorToken, getOperadorGuardado,
  guardarOperador, esquecerOperador, esquecerDispositivo,
  getEstadoCaixa, getCaixaIdGuardada, guardarCaixaId, detalhesErroPos,
  lerEstadoDoModo,
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

function EcraCarregando() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-app-grid">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
    </div>
  );
}

function EcraErro({ mensagem, onTentar }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-app-grid p-6">
      <div className="max-w-sm text-center flex flex-col items-center gap-3">
        <AlertCircle className="h-8 w-8 text-destructive" />
        <p className="text-muted-foreground">{mensagem}</p>
        {onTentar && <Button variant="outline" onClick={onTentar}>Tentar novamente</Button>}
      </div>
    </div>
  );
}

// Barra de cima para o estado "caixa fechada": só identidade + trocar de
// operador — nenhuma das acções do menu Caixa (PosMenuCaixa) se aplica sem
// uma sessão aberta, por isso não é o mesmo componente.
function TopoSimples({ lojaNome, caixa, operador, onSair, modo }) {
  return (
    <header className="border-b bg-card">
      <div className="flex items-center justify-between gap-3 px-4 sm:px-6 h-16">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-9 w-9 rounded-lg brand-gradient flex items-center justify-center font-heading font-bold text-white shrink-0">
            L
          </div>
          <div className="leading-tight min-w-0">
            <p className="font-heading font-bold text-sm truncate">{lojaNome || 'Loja'}</p>
            <p className="text-xs text-muted-foreground truncate">{caixa?.nome}</p>
          </div>
        </div>
        {/* No vão que o `justify-between` já deixava vazio: em `normal` não
            desenha um pixel e esta barra fica exactamente como estava. */}
        <PosFaixaModo estado={modo} />

        <div className="flex items-center gap-2 min-w-0">
          <p className="text-sm font-medium truncate max-w-[9rem] hidden sm:block">{operador?.nome}</p>
          <Button variant="ghost" size="icon" onClick={onSair} title="Trocar de operador" aria-label="Trocar de operador">
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </header>
  );
}

// Resolve a caixa (uma, várias por escolher, ou nenhuma configurada) e
// mostra o ecrã certo (Task 2); com a caixa aberta, o ecrã de venda
// (PosVenda, Tasks 3/4). O PosVenda não leva `key` nenhuma e este
// componente não volta a montá-lo por cada render — é o que faz com que a
// tela de descanso (PosBloqueado, uma sobreposição que não desmonta nada)
// devolva a conta exactamente como estava. A sessão e o operador não lhe
// vão como props: o servidor tira-os do token, e o PosVenda só existe
// enquanto há sessão aberta (fechar a caixa devolve o ecrã ao
// PosCaixaFechada).
function AppInterna({ operador, lojaNome, onSair, onOperadorInvalido, modo }) {
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [caixas, setCaixas] = useState([]);
  const [caixa, setCaixa] = useState(null);
  const [sessaoAberta, setSessaoAberta] = useState(null);
  const [ultimoFecho, setUltimoFecho] = useState(null);
  const [fecharAberto, setFecharAberto] = useState(false);
  // **O sinal do «Copiar para a venda».** O separador Faturação vive na barra
  // de cima (`PosMenuCaixa`) e a conta vive no ecrã de baixo (`PosVenda`), que
  // é quem a lê e a guarda. Copiar uma fatura abre uma conta NOVA no servidor —
  // e sem este sinal o `PosVenda` continuava a mostrar o ecrã vazio, a
  // operadora tocava num produto e o `POST /pos/venda` respondia 409 sobre uma
  // conta que ela não estava a ver: exactamente o beco que o «um posto, uma
  // conta» veio fechar, reaberto por um lado novo.
  //
  // Um CONTADOR e não um booleano: duas cópias seguidas têm de dar dois sinais,
  // e um booleano que já estava a `true` não muda nada.
  const [contasCopiadas, setContasCopiadas] = useState(0);

  const carregar = useCallback(async (caixaId) => {
    setCarregando(true);
    setErro(null);
    try {
      const alvo = caixaId !== undefined ? caixaId : getCaixaIdGuardada();
      const { data } = await getEstadoCaixa(alvo);
      setCaixas(data.caixas || []);
      setCaixa(data.caixa || null);
      setSessaoAberta(data.sessao_aberta || null);
      setUltimoFecho(data.ultimo_fecho || null);
      if (data.caixa) guardarCaixaId(data.caixa.id);
    } catch (error) {
      if (error.response?.status === 401) { onOperadorInvalido(); return; }
      setErro(detalhesErroPos(error, 'Não foi possível obter o estado da caixa.').mensagem);
    } finally {
      setCarregando(false);
    }
  }, [onOperadorInvalido]);

  useEffect(() => { carregar(); }, [carregar]);

  if (carregando) return <EcraCarregando />;
  if (erro) return <EcraErro mensagem={erro} onTentar={() => carregar()} />;

  if (!caixa) {
    if (caixas.length === 0) {
      return <EcraErro mensagem="Não há nenhuma caixa activa configurada para esta loja. Contacte o gestor." />;
    }
    // Mais do que uma caixa activa: o servidor devolve a lista sem
    // escolher (faturacao/caixa.py::estado_caixa) — escolher a primeira
    // seria escolher errado, o mesmo raciocínio do PIN em conflito.
    return (
      <div className="min-h-screen flex items-center justify-center bg-app-grid p-6">
        <div className="max-w-sm w-full text-center">
          <h2 className="font-heading font-bold text-xl mb-1">Qual caixa?</h2>
          <p className="text-muted-foreground text-sm mb-6">Esta loja tem mais do que uma caixa activa.</p>
          <div className="space-y-3">
            {caixas.map((c) => (
              <Button key={c.id} variant="outline" size="lg" className="w-full h-14 text-base" onClick={() => carregar(c.id)}>
                {c.nome}
              </Button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!sessaoAberta) {
    return (
      <div className="min-h-screen flex flex-col bg-app-grid">
        <TopoSimples lojaNome={lojaNome} caixa={caixa} operador={operador} onSair={onSair} modo={modo} />
        <PosCaixaFechada caixa={caixa} ultimoFecho={ultimoFecho} onAberta={() => carregar(caixa.id)} />
      </div>
    );
  }

  return (
    // `h-screen` e não `min-h-screen`: com um MÍNIMO, esta casca cresce com o
    // conteúdo e as zonas de scroll interno do PosVenda (a grelha e a conta,
    // ambas `flex-1 min-h-0 overflow-y-auto`) nunca chegam a apertar — quem
    // rolava era a página inteira, levando o painel da conta atrás. Com a
    // altura FIXA do ecrã, cada uma rola dentro do seu espaço e o painel da
    // direita fica quieto, que é como um balcão se usa.
    <div className="h-screen overflow-hidden flex flex-col bg-app-grid">
      <PosMenuCaixa
        modo={modo}
        operador={operador}
        lojaNome={lojaNome}
        caixa={caixa}
        sessao={sessaoAberta}
        onSair={onSair}
        onFecharCaixa={() => setFecharAberto(true)}
        onMovimentoRegistado={() => {}}
        onContaCopiada={() => setContasCopiadas((n) => n + 1)}
      />
      <PosVenda
        caixa={caixa}
        onOperadorInvalido={onOperadorInvalido}
        contasCopiadas={contasCopiadas}
      />
      <PosFecharCaixa
        aberto={fecharAberto}
        onFechar={() => setFecharAberto(false)}
        caixa={caixa}
        sessao={sessaoAberta}
        onFechado={() => { setFecharAberto(false); carregar(caixa.id); }}
      />
    </div>
  );
}

export default function PosApp() {
  // O separador do browser diz "Lisbonb - POS" enquanto isto estiver à frente.
  // Fica aqui, e não no `index.html`, porque aquele título é do portal inteiro
  // — ver `useTituloDoPos`.
  useTituloDoPos();

  const [dispositivo, setDispositivo] = useState(() => {
    const token = getDeviceToken();
    return token ? { token, lojaId: getLojaId(), lojaNome: getLojaNome() } : null;
  });
  const [operador, setOperador] = useState(() => {
    const token = getOperatorToken();
    const dados = getOperadorGuardado();
    return token && dados ? { token, dados } : null;
  });

  // **Em que modo é que este POS está a emitir** — `tests`, `normal`, ou o
  // terceiro estado, «não se sabe». O valor inicial é deliberadamente
  // `undefined`: antes de o servidor responder o ecrã NÃO SABE, e
  // `faixaDoModo(undefined)` desenha o aviso do terceiro estado em vez de o
  // silêncio de `normal`. Começar em `'normal'` (ou em `null` tratado como
  // silêncio) era escolher um dos dois lados por omissão, e é esse o engano
  // que a faixa inteira existe para não deixar acontecer.
  //
  // **Vive AQUI, no `PosApp`, e não lá dentro**, porque aqui é o que não
  // desmonta: sair (`Trocar de operador`) devolve o ecrã ao `PosEntrar` e
  // desmonta o `AppInterna` e tudo o que está por baixo. Lido lá dentro, o
  // modo perdia-se a cada troca de operador e a faixa recomeçava em
  // «desconhecido» de cada vez — que é a maneira certa de ensinar toda a gente
  // a ignorá-la.
  //
  // `lerEstadoDoModo` NUNCA rejeita: o `catch` está dentro dela (lib/pos.js),
  // e é por isso que aqui não há `.catch` nenhum a fazer falta. Sem rede, sem
  // rota, com um 401 ou com uma resposta que não se percebe, o que chega é
  // `'desconhecido'`.
  //
  // Relido de minuto a minuto: o modo só muda quando alguém mexe no servidor,
  // mas é assim que o ecrã SAI do terceiro estado sozinho quando a rede volta
  // — sem obrigar a operadora a adivinhar que tem de fazer F5.
  const [modo, setModo] = useState(undefined);

  useEffect(() => {
    if (!dispositivo) return undefined;
    let vivo = true;
    const ler = () => lerEstadoDoModo().then((estado) => { if (vivo) setModo(estado); });
    ler();
    const relogio = setInterval(ler, 60000);
    return () => { vivo = false; clearInterval(relogio); };
  }, [dispositivo]);

  const dispositivoInvalido = useCallback(() => {
    esquecerDispositivo();
    setDispositivo(null);
    setOperador(null);
    toast.error('Este dispositivo já não está emparelhado. Peça um novo código ao gestor.');
  }, []);

  const operadorInvalido = useCallback(() => {
    esquecerOperador();
    setOperador(null);
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
      <AppInterna
        operador={operador.dados}
        lojaNome={dispositivo.lojaNome}
        onSair={sair}
        onOperadorInvalido={operadorInvalido}
        modo={modo}
      />
    </PosBloqueado>
  );
}
