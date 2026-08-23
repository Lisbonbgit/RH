import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Wallet, Info, BanknoteArrowDown, BanknoteArrowUp, Store, DoorOpen, GraduationCap, Lock, LogOut,
  Loader2, HelpCircle, Check,
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
import PosFaixaModo from './PosFaixaModo';
import PosResumoDoTurno from './PosResumoDoTurno';
import PosFaturacao from './PosFaturacao';
import useEstadoDaImpressao from './useEstadoDaImpressao';
import {
  registarMovimento, getPontoDeCaixa, detalhesErroPos, eurosPos,
  temMaisDe2CasasDecimaisPos, abrirGavetaPos, razaoDeNaoImprimir,
  avisoDaFilaDeImpressao, haFalhadosPorVer, darFalhadosPorVistos,
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

function DialogoMovimento({ tipo, aberto, onFechar, caixaId, onRegistado }) {
  const [valor, setValor] = useState('');
  const [motivo, setMotivo] = useState('');
  const [aEnviar, setAEnviar] = useState(false);
  // Quanto está na gaveta AGORA — `null` enquanto se pergunta, `{ esperado }`
  // depois, `{ erro }` se a pergunta falhou. Os três distintos de propósito:
  // "não se sabe" e "está vazia" não podem ter o mesmo aspecto num ecrã que
  // autoriza tirar dinheiro.
  const [naGaveta, setNaGaveta] = useState(null);
  const motivoObrigatorio = tipo === 'saida';
  const titulo = tipo === 'entrada' ? 'Entrada de Dinheiro' : 'Saída de Dinheiro';

  useEffect(() => {
    if (aberto) { setValor(''); setMotivo(''); }
  }, [aberto]);

  // **O número que evita o engano tem de estar à frente dela ENQUANTO
  // escreve.** O servidor recusa a saída que tira mais do que está na gaveta
  // (`caixa.py::registar_movimento`), e essa recusa é a defesa — mas chega
  // depois do toque, e uma recusa sem contexto lê-se como uma avaria. Aqui
  // está o mesmo número que o Ponto de Caixa mostra, vindo SOMADO do servidor
  // (`GET /pos/caixa/ponto`, só leitura): o browser não faz aritmética de
  // dinheiro, e por isso o ecrã não desconta o que ela está a escrever — diz
  // o que lá está, e a conta é dela.
  //
  // **Só nas SAÍDAS.** Uma entrada não pode passar limite nenhum, e perguntar
  // à toa é um pedido por cada troco reforçado.
  useEffect(() => {
    if (!aberto || tipo !== 'saida' || !caixaId) return undefined;
    let vivo = true;
    setNaGaveta(null);
    getPontoDeCaixa(caixaId)
      .then(({ data }) => { if (vivo) setNaGaveta({ esperado: data?.esperado }); })
      .catch((error) => {
        if (!vivo) return;
        setNaGaveta({
          erro: detalhesErroPos(
            error, 'Não foi possível saber quanto está na gaveta.',
          ).mensagem,
        });
      });
    return () => { vivo = false; };
  }, [aberto, tipo, caixaId]);

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
          {/* Por CIMA do campo, e não por baixo: é para ser lido antes de o
              dedo escrever o primeiro algarismo. */}
          {motivoObrigatorio && (
            <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
              {naGaveta === null ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin shrink-0 mt-0.5" />
                  <span>A ver quanto está na gaveta…</span>
                </>
              ) : (
                <>
                  <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>
                    {naGaveta.erro
                      ? `${naGaveta.erro} O servidor recusa uma saída maior do que o que lá está — se esta for recusada, é por isso.`
                      : `Na gaveta estão ${eurosPos(naGaveta.esperado)} (fundo + vendas em dinheiro + entradas − saídas deste turno). O servidor recusa uma saída maior do que isto.`}
                  </span>
                </>
              )}
            </div>
          )}
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
export default function PosMenuCaixa({
  operador, lojaNome, caixa, sessao, onSair, onFecharCaixa, onMovimentoRegistado, modo,
  onContaCopiada,
}) {
  const [dialogoMovimento, setDialogoMovimento] = useState(null); // 'entrada' | 'saida' | null
  const [aAbrirGaveta, setAAbrirGaveta] = useState(false);
  // **Cada ecrã com botões de imprimir pergunta o seu estado.** Já esteve
  // perguntado uma vez no `PosApp` e descido por props, e isso deixava um
  // buraco que nenhum teste tapava: bastava alguém esquecer a prop num dos
  // ramos para os botões ficarem mortos para sempre, com o ecrã a dizer «a
  // perguntar…» o dia inteiro. Três pedidos a um endpoint que devolve quatro
  // números, de 20 em 20 segundos, custam menos do que essa avaria.
  const { estado: estadoImpressao, recarregar: recarregarImpressao } =
    useEstadoDaImpressao();
  const razaoDeNaoAbrirGaveta = razaoDeNaoImprimir({
    estado: estadoImpressao, aImprimir: aAbrirGaveta,
  });
  const avisoDaFila = avisoDaFilaDeImpressao(estadoImpressao);
  const [aDarPorVisto, setADarPorVisto] = useState(false);

  // **«Já vi»** — o que desliga o aviso dos papéis que não saíram.
  //
  // Não apaga nem resolve nada: o papel continua a reimprimir-se pelo
  // separador Faturação. O que tira é o AVISO, depois de a pessoa o ler — e
  // era a única coisa que não tinha maneira de sair do ecrã antes de o TTL de
  // 7 dias do Mongo apagar o trabalho.
  const darPorVisto = useCallback(async () => {
    if (aDarPorVisto) return;
    setADarPorVisto(true);
    try {
      await darFalhadosPorVistos();
    } catch (error) {
      const { mensagem } = detalhesErroPos(
        error, 'Não foi possível dar o aviso por visto.');
      toast.error(mensagem);
    } finally {
      setADarPorVisto(false);
      recarregarImpressao();
    }
  }, [aDarPorVisto, recarregarImpressao]);

  // Não diz "a gaveta abriu": diz que o pedido foi para a fila. Quem abre a
  // gaveta é a impressora da loja, e este ecrã não a vê. O impulso vale DOIS
  // minutos (`impressao._VALIDADE_MINUTOS`) — um que chegasse dez minutos
  // atrasado abria a gaveta do dinheiro com ninguém à frente dela.
  const abrirGaveta = useCallback(async () => {
    if (aAbrirGaveta) return;
    setAAbrirGaveta(true);
    try {
      await abrirGavetaPos();
      toast.success('Pedido de abertura enviado à impressora do balcão.');
    } catch (error) {
      const { mensagem } = detalhesErroPos(
        error, 'Não foi possível pedir a abertura da gaveta.');
      toast.error(mensagem);
    } finally {
      setAAbrirGaveta(false);
      recarregarImpressao();
    }
  }, [aAbrirGaveta, recarregarImpressao]);
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

        {/* A faixa do modo de emissão vai AQUI, no vão que o
            `justify-between` já deixava vazio entre a identidade da loja e o
            botão «Caixa» — não numa linha por cima da barra. Em `normal` não
            desenha um único pixel e este topo fica exactamente como estava; nos
            outros dois estados o que muda é a cor da barra inteira, sem um
            pixel a mais de altura. Ver PosFaixaModo.js. */}
        <PosFaixaModo estado={modo} />

        {/* Ao lado do «Caixa», que é onde o dono a pediu: «uma aba ao lado do
            caixa com umas opções». Ver PosFaturacao.js. */}
        <div className="flex items-center gap-2">
        <PosFaturacao caixa={caixa} onContaCopiada={onContaCopiada} />

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
            {/* **A gaveta abre PELA IMPRESSORA** — é um impulso ESC/POS pelo
                cabo da gaveta, não um aparelho à parte (é assim que está
                montado nas lojas). Por isso passa pela mesma fila que o papel:
                sem programa de impressão a ouvir, não abre — e diz-se, em vez
                de a operadora ficar a carregar num botão morto. */}
            <DropdownMenuItem
              disabled={!!razaoDeNaoAbrirGaveta}
              onSelect={(e) => { e.preventDefault(); abrirGaveta(); }}
              className={razaoDeNaoAbrirGaveta ? 'opacity-60' : undefined}
              title={razaoDeNaoAbrirGaveta || undefined}
            >
              <DoorOpen className="h-4 w-4 mr-2" /> Abrir Gaveta
              {aAbrirGaveta && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin" />}
            </DropdownMenuItem>
            {razaoDeNaoAbrirGaveta && (
              <p className="px-2 pb-1 text-[10px] text-muted-foreground leading-snug">
                {razaoDeNaoAbrirGaveta}
              </p>
            )}
            {avisoDaFila && (
              <p className="px-2 pb-1 text-[10px] text-muted-foreground leading-snug">
                {avisoDaFila}
              </p>
            )}
            {haFalhadosPorVer(estadoImpressao) && (
              <DropdownMenuItem
                disabled={aDarPorVisto}
                onSelect={(e) => { e.preventDefault(); darPorVisto(); }}
              >
                <Check className="h-4 w-4 mr-2" /> Já vi os papéis que falharam
                {aDarPorVisto && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin" />}
              </DropdownMenuItem>
            )}
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
        </div>

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
            <p><span className="text-muted-foreground">Fundo de abertura:</span> {eurosPos(sessao?.fundo)}</p>
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
