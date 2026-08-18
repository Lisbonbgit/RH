import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, AlertCircle, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PosEmparelhar from './PosEmparelhar';
import PosEntrar from './PosEntrar';
import PosBloqueado from './PosBloqueado';
import PosCaixaFechada from './PosCaixaFechada';
import PosMenuCaixa from './PosMenuCaixa';
import PosFecharCaixa from './PosFecharCaixa';
import {
  getDeviceToken, getLojaId, getLojaNome, getOperatorToken, getOperadorGuardado,
  guardarOperador, esquecerOperador, esquecerDispositivo,
  getEstadoCaixa, getCaixaIdGuardada, guardarCaixaId, detalhesErroPos,
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
function TopoSimples({ lojaNome, caixa, operador, onSair }) {
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
// mostra o ecrã certo (Task 2). A venda propriamente dita (Tasks 3/4 do
// plano) ainda não existe — fica um espaço honesto em vez de fingir um
// ecrã que ainda não foi construído.
function AppInterna({ operador, lojaNome, onSair, onOperadorInvalido }) {
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [caixas, setCaixas] = useState([]);
  const [caixa, setCaixa] = useState(null);
  const [sessaoAberta, setSessaoAberta] = useState(null);
  const [ultimoFecho, setUltimoFecho] = useState(null);
  const [fecharAberto, setFecharAberto] = useState(false);

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
        <TopoSimples lojaNome={lojaNome} caixa={caixa} operador={operador} onSair={onSair} />
        <PosCaixaFechada caixa={caixa} ultimoFecho={ultimoFecho} onAberta={() => carregar(caixa.id)} />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-app-grid">
      <PosMenuCaixa
        operador={operador}
        lojaNome={lojaNome}
        caixa={caixa}
        sessao={sessaoAberta}
        onSair={onSair}
        onFecharCaixa={() => setFecharAberto(true)}
        onMovimentoRegistado={() => {}}
      />
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="text-muted-foreground text-center max-w-sm">
          A venda (grelha de produtos, conta e finalizar) é a fase seguinte deste ecrã —
          ainda por construir. Abrir e fechar a caixa já funcionam a sério.
        </p>
      </div>
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
      />
    </PosBloqueado>
  );
}
