import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Wallet, Info, BanknoteArrowDown, BanknoteArrowUp, Store, DoorOpen, GraduationCap, Lock, LogOut,
  Loader2, HelpCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import PosCampoValor from './PosCampoValor';
import PosResumoDoTurno from './PosResumoDoTurno';
import {
  registarMovimento, getPontoDeCaixa, detalhesErroPos, temMaisDe2CasasDecimaisPos,
} from '@/lib/pos';

const formatarData = (isoString) => {
  if (!isoString) return null;
  try {
    const d = new Date(isoString);
    const data = d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit', year: 'numeric' });
    const hora = d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
    return `${data} às ${hora}`;
  } catch (e) {
    return null;
  }
};

const formatarEuros = (valor) =>
  (Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function DialogoMovimento({ tipo, aberto, onFechar, caixaId, onRegistado }) {
  const [valor, setValor] = useState('');
  const [motivo, setMotivo] = useState('');
  const [aEnviar, setAEnviar] = useState(false);
  const motivoObrigatorio = tipo === 'saida';
  const titulo = tipo === 'entrada' ? 'Entrada de Dinheiro' : 'Saída de Dinheiro';

  useEffect(() => {
    if (aberto) { setValor(''); setMotivo(''); }
  }, [aberto]);

  const podeSubmeter =
    valor !== '' && !temMaisDe2CasasDecimaisPos(valor) && Number(valor) > 0 &&
    (!motivoObrigatorio || motivo.trim().length > 0) && !aEnviar;

  const submeter = async () => {
    if (!podeSubmeter) return;
    setAEnviar(true);
    try {
      // PedidoMovimento é deliberadamente sem sessao_id (faturacao/caixa.py):
      // o servidor resolve sempre a sessão aberta a partir da caixa —
      // nunca de um valor que o pedido diga que é a sessão.
      await registarMovimento({
        caixa_id: caixaId, tipo, valor: Number(valor), motivo: motivo.trim() || undefined,
      });
      toast.success(tipo === 'entrada' ? 'Entrada registada' : 'Saída registada');
      onRegistado();
      onFechar();
    } catch (error) {
      const { mensagem } = detalhesErroPos(error, 'Não foi possível registar o movimento.');
      toast.error(mensagem);
    } finally {
      setAEnviar(false);
    }
  };

  return (
    <Dialog open={aberto} onOpenChange={(v) => { if (!v) onFechar(); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{titulo}</DialogTitle></DialogHeader>
        <div className="space-y-4 py-2">
          <PosCampoValor id={`valor-${tipo}`} label="Valor" valor={valor} onChange={setValor} autoFocus disabled={aEnviar} />
          <div className="space-y-1.5">
            <Label htmlFor={`motivo-${tipo}`}>Motivo{motivoObrigatorio ? '' : ' (opcional)'}</Label>
            <Input
              id={`motivo-${tipo}`}
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              disabled={aEnviar}
              placeholder={motivoObrigatorio ? 'Obrigatório numa saída de dinheiro' : 'Ex.: troco extra ao balcão'}
              maxLength={200}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onFechar} disabled={aEnviar}>Cancelar</Button>
          <Button onClick={submeter} disabled={!podeSubmeter}>
            {aEnviar ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Confirmar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// O Ponto de Caixa: a conferência a meio do turno, sem fechar nada.
//
// A operadora quer saber se a gaveta bate certo às 15h, em vez de descobrir
// às 23h que houve um erro de troco que já não consegue reconstituir. E
// serve a rendição de turno — uma sai, outra entra, sem fechar a caixa.
//
// **Não fecha, não assina, não muda nada.** Não há aqui botão nenhum de
// confirmar: fecha-se a janela e a caixa fica como estava. É a razão de o
// servidor responder a isto com um GET que não escreve uma única vez.
//
// Os números **não se calculam aqui**. Chegam todos somados do servidor,
// pela mesma função que produz o Z (`caixa._resumo_do_turno`) — se este
// ecrã somasse euros por sua conta, a conferência das 15h e o Z das 23h
// seriam dois cálculos diferentes sobre o mesmo dinheiro, e o mais provável
// era a operadora passar a tarde a procurar uma diferença que não existe.
function DialogoPontoDeCaixa({ aberto, onFechar, lojaNome, caixa, operador }) {
  const [resumo, setResumo] = useState(null);
  const [erro, setErro] = useState(null);

  // Lido de FRESCO a cada abertura, e o anterior deitado fora primeiro: um
  // ponto de caixa é uma fotografia de um instante, e mostrar o da última
  // vez enquanto o novo não chega é mostrar um número velho sem o dizer.
  useEffect(() => {
    if (!aberto || !caixa?.id) return;
    let vivo = true;
    setResumo(null);
    setErro(null);
    getPontoDeCaixa(caixa.id)
      .then(({ data }) => { if (vivo) setResumo(data); })
      .catch((error) => {
        if (!vivo) return;
        const { mensagem } = detalhesErroPos(error, 'Não foi possível ler o ponto de caixa.');
        setErro(mensagem);
      });
    return () => { vivo = false; };
  }, [aberto, caixa?.id]);

  return (
    <Dialog open={aberto} onOpenChange={(v) => { if (!v) onFechar(); }}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader><DialogTitle>Ponto de Caixa</DialogTitle></DialogHeader>

        <div className="text-sm text-muted-foreground space-y-0.5">
          <p>{lojaNome || 'Loja'} · {caixa?.nome} · {operador?.nome}</p>
          <p>
            Turno aberto por {resumo?.sessao?.aberta_por?.nome || '—'}
            {formatarData(resumo?.sessao?.aberta_em) ? ` em ${formatarData(resumo.sessao.aberta_em)}` : ''}
          </p>
          {/* A hora da conferência, impressa. A folha fica na bancada
              depois de a venda seguinte entrar; sem isto, meia hora depois
              ninguém sabe se o número ainda vale. */}
          {resumo?.momento && <p>Conferência às {formatarData(resumo.momento)}</p>}
        </div>

        <Separator />

        {erro ? (
          <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
            <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{erro}</span>
          </div>
        ) : !resumo ? (
          <div className="flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            <span>A somar o turno…</span>
          </div>
        ) : (
          <PosResumoDoTurno resumo={resumo} />
        )}

        <DialogFooter>
          {/* "Fechar" a janela, e nunca "Confirmar": não há nada para
              confirmar, e um botão de confirmação num ecrã que não muda nada
              convida a operadora a pensar que fechou a caixa. */}
          <Button variant="outline" className="w-full h-11" onClick={onFechar}>
            Fechar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// A barra de cima da app (Task 2, do print do Vendus): identidade da
// loja/caixa, o menu Caixa (Estado da Caixa · Entrada · Saída · Ponto de
// Caixa · Abrir Gaveta · Modo de Formação · Fechar Caixa) e quem está
// ligado. Abrir Gaveta e Modo de Formação ficam visíveis mas desligados —
// nenhum dos dois tem suporte no servidor ainda — com uma explicação em vez
// de um botão morto sem dizer porquê.
export default function PosMenuCaixa({ operador, lojaNome, caixa, sessao, onSair, onFecharCaixa, onMovimentoRegistado }) {
  const [dialogoMovimento, setDialogoMovimento] = useState(null); // 'entrada' | 'saida' | null
  const [estadoAberto, setEstadoAberto] = useState(false);
  const [pontoAberto, setPontoAberto] = useState(false);

  return (
    <header className="border-b bg-card sticky top-0 z-10">
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

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="lg" className="h-11">
              <Wallet className="h-4 w-4 mr-1" /> Caixa
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center" className="w-72">
            <DropdownMenuItem onSelect={() => setEstadoAberto(true)}>
              <Info className="h-4 w-4 mr-2" /> Estado da Caixa
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setDialogoMovimento('entrada')}>
              <BanknoteArrowDown className="h-4 w-4 mr-2" /> Entrada de Dinheiro
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setDialogoMovimento('saida')}>
              <BanknoteArrowUp className="h-4 w-4 mr-2" /> Saída de Dinheiro
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setPontoAberto(true)}>
              <Store className="h-4 w-4 mr-2" /> Ponto de Caixa
            </DropdownMenuItem>
            <DropdownMenuItem disabled className="opacity-60">
              <DoorOpen className="h-4 w-4 mr-2" /> Abrir Gaveta
              <span className="ml-auto text-[10px] text-muted-foreground">Brevemente</span>
            </DropdownMenuItem>
            <DropdownMenuItem disabled className="opacity-60">
              <GraduationCap className="h-4 w-4 mr-2" /> Modo de Formação
              <span className="ml-auto text-[10px] text-muted-foreground">Brevemente</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onFecharCaixa} className="text-destructive focus:text-destructive">
              <Lock className="h-4 w-4 mr-2" /> Fechar Caixa
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="flex items-center gap-2 min-w-0">
          <p className="text-sm font-medium truncate max-w-[9rem] hidden sm:block">{operador?.nome}</p>
          <Button variant="ghost" size="icon" onClick={onSair} title="Trocar de operador" aria-label="Trocar de operador">
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </div>

      <DialogoMovimento
        tipo={dialogoMovimento}
        aberto={!!dialogoMovimento}
        onFechar={() => setDialogoMovimento(null)}
        caixaId={caixa?.id}
        onRegistado={onMovimentoRegistado}
      />

      <Dialog open={estadoAberto} onOpenChange={setEstadoAberto}>
        <DialogContent>
          <DialogHeader><DialogTitle>Estado da Caixa</DialogTitle></DialogHeader>
          <div className="space-y-2 text-sm">
            <p><span className="text-muted-foreground">Caixa:</span> {caixa?.nome}</p>
            <p><span className="text-muted-foreground">Aberta por:</span> {sessao?.aberta_por?.nome || '—'}</p>
            <p><span className="text-muted-foreground">Aberta em:</span> {formatarData(sessao?.aberta_em) || '—'}</p>
            <p><span className="text-muted-foreground">Fundo de abertura:</span> € {formatarEuros(sessao?.fundo)}</p>
          </div>
        </DialogContent>
      </Dialog>

      <DialogoPontoDeCaixa
        aberto={pontoAberto}
        onFechar={() => setPontoAberto(false)}
        lojaNome={lojaNome}
        caixa={caixa}
        operador={operador}
      />
    </header>
  );
}
