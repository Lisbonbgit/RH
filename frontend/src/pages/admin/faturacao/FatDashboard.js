import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
// **Os gráficos vivem num módulo à parte** — o ecrã dos Relatórios usa os
// mesmos. Duas cópias da conta que converte a posição do rato para o
// `viewBox` divergiam à primeira correcção, e é essa conta que já apanhou
// três defeitos.
import {
  AREA, GraficoDeArea, buildArea, buildBars, roundedBarPath,
  indiceMaisPerto, BalaoDoGrafico, fmtEURShort, eixoDeValores, eixoDeRotulos,
} from './GraficosDaFaturacao';
import { getFatDashboard } from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Switch } from '../../../components/ui/switch';
import { Label } from '../../../components/ui/label';
import { Button } from '../../../components/ui/button';
import {
  LayoutDashboard, ShoppingCart, CalendarDays, BarChart3, ArrowUpRight, ArrowDownRight,
  Store, Info, RefreshCw, Rocket, Star, TrendingUp, PackageSearch, Tag,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import FatModoDeEmissao from './FatModoDeEmissao';
import { toast } from 'sonner';

// Euro à portuguesa via Intl.NumberFormat('pt-PT', ...): símbolo DEPOIS do
// número, vírgula nos decimais — ex.: 1503.20 -> "1503,20 €" (o pt-PT só
// agrupa milhares a partir de 5 dígitos: 12345.67 -> "12 345,67 €", com
// espaço, não ponto). Não é "€ 1.503,20" como este comentário dizia antes —
// confirmado com Intl.NumberFormat directamente, não de memória. O formato
// é o mesmo em todo o portal (lib/finance.js, MarketingReports.js); não
// mudar aqui isoladamente.
const fmtEUR = (n) => new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(Number(n) || 0);

// Quantidades: inteiro quando é inteiro. Uma devolução parcial pode deixar
// 2,5 no meio de uma lista de números redondos — mostrar "2,500" a todos
// para acomodar esse caso era feio nos 99% dos dias em que não acontece.
const fmtQtd = (n) => new Intl.NumberFormat('pt-PT', { maximumFractionDigits: 3 }).format(Number(n) || 0);

const fmtPct = (n) => {
  const v = Number(n) || 0;
  return `${v >= 0 ? '+' : ''}${v.toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
};

// 'YYYY-MM-DD' -> 'dd-mm' (parte a string; sem Date, para nunca tropeçar em fusos).
const ddmm = (iso) => {
  const [, m, d] = String(iso || '').slice(0, 10).split('-');
  return d && m ? `${d}-${m}` : String(iso || '');
};

const MESES_ABREV = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
// 'YYYY-MM' -> 'Ago'
const mesLabel = (m) => {
  const mm = parseInt(String(m || '').slice(5, 7), 10);
  const label = MESES_ABREV[mm - 1] || m;
  return label.charAt(0).toUpperCase() + label.slice(1);
};




// Mini gráfico de área (sparkline) para a linha de uma loja — sem eixos nem
// grelha, só a forma da tendência dos últimos 30 dias.
function MiniArea({ pontos, gradId }) {
  const area = useMemo(
    () => buildArea(pontos, { xLeft: 2, xRight: 118, yTop: 4, yBase: 36, yFill: 38 }),
    [pontos]
  );
  // O toque vive DENTRO do mini-gráfico, e não no ecrã: são cinco lojas, e o
  // estado de cada linha é dela. Uma variável no ecrã para todas fazia o balão
  // de uma loja aparecer em cima da linha da outra.
  const [ponto, setPonto] = useState(null);
  const svg = useRef(null);
  if (!area) return null;
  const escolhido = ponto != null ? area.coords[ponto] : null;
  return (
    <div
      className="relative w-24 shrink-0"
      onPointerMove={(e) => setPonto(indiceMaisPerto(e, svg.current, area.coords, 120))}
      onPointerLeave={() => setPonto(null)}
    >
      <svg viewBox="0 0 120 40" className="w-full h-8" ref={svg} xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.35" />
            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <path d={area.areaPath} fill={`url(#${gradId})`} />
        <path d={area.line} fill="none" stroke="hsl(var(--primary))" strokeWidth="1.5"
          strokeLinejoin="round" strokeLinecap="round" />
        {escolhido && (
          <g>
            <line x1={escolhido.x} y1="2" x2={escolhido.x} y2="38"
              stroke="hsl(var(--primary))" strokeWidth="0.8" strokeOpacity="0.45" />
            <circle cx={escolhido.x} cy={escolhido.y} r="2.5" fill="hsl(var(--primary))"
              stroke="hsl(var(--card))" strokeWidth="1" />
          </g>
        )}
      </svg>
      {escolhido && (
        <BalaoDoGrafico
          compacto
          xPct={escolhido.x / 120}
          yPct={escolhido.y / 40}
          valor={fmtEUR(escolhido.v)}
          etiqueta={ddmm(escolhido.data)}
        />
      )}
    </div>
  );
}

// Mini gráfico de barras (últimos 6 meses) para a linha de uma loja — sem
// eixos nem legendas, só a forma da tendência mensal.
function MiniBars({ pontos }) {
  const b = useMemo(
    () => buildBars(pontos, { xLeft: 0, slot: 16, barW: 11, yTop: 4, yBase: 34, minH: 1.5 }),
    [pontos]
  );
  const [tocada, setTocada] = useState(null);
  if (!b) return null;
  const escolhida = tocada != null ? b.bars[tocada] : null;
  return (
    <div className="relative w-24 shrink-0" onPointerLeave={() => setTocada(null)}>
      <svg viewBox="0 0 96 40" className="w-full h-10" xmlns="http://www.w3.org/2000/svg">
        {b.bars.map((bar, i) => (
          <g key={i}>
            <path d={roundedBarPath(bar.x, bar.y, bar.w, bar.h, 2, bar.neg ? 'bottom' : 'top')}
              fill="hsl(var(--primary))"
              fillOpacity={tocada != null && tocada !== i ? 0.35 : (bar.neg ? 0.55 : 0.85)} />
            {/* A coluna inteira como alvo: estas barras têm 11 unidades de
                largura num desenho de 96 — apontar à tinta era impossível. */}
            <rect x={bar.cx - 8} y={0} width={16} height={40} fill="transparent"
              onPointerEnter={() => setTocada(i)} />
          </g>
        ))}
      </svg>
      {escolhida && (
        <BalaoDoGrafico
          compacto
          xPct={escolhida.cx / 96}
          yPct={escolhida.y / 40}
          valor={fmtEUR(escolhida.v)}
          etiqueta={mesLabel(escolhida.mes)}
        />
      )}
    </div>
  );
}

// Pastilha da variação — verde quando >=0, vermelha quando negativa; e a
// frase por extenso quando não há período anterior comparável (nunca "0%"
// nem "—" sem explicação).
function VariacaoPill({ variacao }) {
  if (variacao == null) {
    return <span className="text-xs text-muted-foreground">Sem período anterior comparável</span>;
  }
  const up = variacao >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-semibold ${
      up ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}`}>
      {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
      {fmtPct(variacao)}
    </span>
  );
}

// Estado vazio compacto: nada se vendeu no período, e por isso não há top.
function EmptyMini({ icon: Icon, texto = 'Sem informação disponível' }) {
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <Icon className="h-9 w-9 text-muted-foreground/50" strokeWidth={1.5} />
      <p className="text-sm text-muted-foreground">{texto}</p>
    </div>
  );
}

// **O topo de artigos** — a mesma lista nos dois cartões.
//
// A barra dá a proporção contra o primeiro da lista. Cinco números em coluna
// obrigam a dividir de cabeça para ver que o primeiro vale o triplo do
// segundo; a barra responde a isso antes de se ler um algarismo.
//
// `Math.abs` no denominador e na largura porque uma nota de crédito pode pôr
// um resultado negativo na lista — uma barra de largura negativa desaparecia
// e a linha ficava a parecer um erro de desenho em vez de um prejuízo.
function TopoDeArtigos({ itens, prefixo, principal, secundario }) {
  const maior = itens.reduce((m, i) => Math.max(m, Math.abs(principal(i).valor)), 0) || 1;
  return (
    <div className="w-full space-y-3 py-1">
      {itens.map((item, i) => {
        const p = principal(item);
        const segundo = secundario ? secundario(item) : null;
        // **Um prejuízo não se pinta da cor do lucro.** Um artigo vendido
        // abaixo do custo aparece aqui de propósito (ver o crivo em
        // `dashboard.topos_de_artigos`), mas com o número e a barra na cor do
        // sistema para o que corre mal — de relance, uma linha azul entre
        // linhas azuis lê-se como mais uma que deu dinheiro.
        const perde = p.valor < 0;
        return (
          <div key={item.produto_id || item.nome || i} data-testid={`${prefixo}-${i}`}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate" title={item.nome}>{item.nome}</span>
              <span className="shrink-0 tabular-nums">
                <span className={perde ? 'font-semibold text-destructive' : 'font-semibold'}>{p.texto}</span>
                {segundo ? <span className="text-muted-foreground"> · {segundo}</span> : null}
              </span>
            </div>
            {/* **Os tamanhos, por baixo do artigo.** «Açaí 25» é verdade e
                não responde a nada — vinte e cinco de qual? No nosso catálogo
                o açaí é um produto só e o tamanho é uma personalização dele.
                Só aparece onde existe: uma água não tem tamanho. */}
            {(item.tamanhos || []).length > 0 ? (
              <p className="mt-0.5 text-xs text-muted-foreground truncate tabular-nums"
                title={item.tamanhos.map((t) => `${t.nome} ${fmtQtd(t.quantidade)}`).join(' · ')}
                data-testid={`${prefixo}-${i}-tamanhos`}>
                {item.tamanhos.map((t) => `${t.nome} ${fmtQtd(t.quantidade)}`).join(' · ')}
              </p>
            ) : null}
            <div className="mt-1.5 h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className={perde ? 'h-full rounded-full bg-destructive' : 'h-full rounded-full bg-primary'}
                // Nunca menos de 2%: uma barra de largura zero lê-se como
                // "não vendeu nada", que é falso — vendeu pouco.
                style={{ width: `${Math.max(2, (Math.abs(p.valor) / maior) * 100)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// **O cartão da margem quando houve vendas mas não há margem para mostrar.**
//
// "Sem informação disponível" é verdade e não serve para nada: não diz porquê
// nem o que fazer, e foi exactamente o que este cartão disse durante meses. A
// margem é Vendas − Custos; sem preço de custo no artigo, não há Custos e não
// há margem. Isso escreve-se, com o caminho para o resolver ao lado — o
// cartão acende sozinho no dia seguinte.
//
// **Três frases e não uma**, porque a lista vazia tem três causas diferentes e
// só uma delas se resolve preenchendo custos. Uma frase única sobre "faltam os
// preços de custo" num dia em que os custos estão todos lá — e o que houve foi
// uma devolução — mandava o dono procurar um problema que não existe.
function SemMargem({ semCusto, vendidos }) {
  const todos = semCusto >= vendidos;
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center" data-testid="fat-sem-precos-de-custo">
      <Tag className="h-9 w-9 text-muted-foreground/50" strokeWidth={1.5} />
      {semCusto === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nenhum artigo com margem para mostrar hoje.
        </p>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {todos && vendidos === 1
              ? 'O artigo vendido hoje não tem preço de custo.'
              : todos
                ? `Nenhum dos ${vendidos} artigos vendidos hoje tem preço de custo.`
                : `${semCusto} dos ${vendidos} artigos vendidos hoje não têm preço de custo.`}
          </p>
          <p className="text-xs text-muted-foreground">Sem ele não há margem para calcular.</p>
          <Button asChild variant="outline" size="sm" className="mt-1">
            <Link to="/admin/faturacao/produtos/lista">Preencher nos Produtos</Link>
          </Button>
        </>
      )}
    </div>
  );
}

const CARTOES = [
  { key: 'hoje', prefixo: 'Faturação', sufixo: 'Hoje', icon: ShoppingCart },
  { key: 'mensal', prefixo: 'Faturação', sufixo: 'Mensal', icon: CalendarDays },
  { key: 'anual', prefixo: 'Faturação', sufixo: 'Anual', icon: BarChart3 },
];

export default function FatDashboard() {
  const [comIva, setComIva] = useState(true);
  // Que ponto da curva e que barra estão debaixo do rato (ou do foco do
  // teclado). `null` = nenhum, e nenhum é o estado normal: um balão sempre
  // visível tapa o desenho e deixa de ser resposta a uma pergunta.
  const [barraTocada, setBarraTocada] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErro(false);
    try {
      const { data } = await getFatDashboard(comIva);
      setDashboard(data);
    } catch (error) {
      toast.error('Erro ao carregar o dashboard de faturação');
      setErro(true);
    } finally {
      setLoading(false);
    }
  }, [comIva]);

  useEffect(() => { load(); }, [load]);

  // ---------- Gráfico de ÁREA (faturação diária, últimos 30 dias) ----------
  //
  // Só os PONTOS: o desenho, a grelha, o eixo, a mira e o balão são do
  // `GraficoDeArea`, partilhado com o ecrã dos Relatórios.
  const pontosDaArea = useMemo(
    () => (dashboard?.serie_diaria || []).map(
      (p) => ({ rotulo: ddmm(p.data), v: Number(p.valor) || 0 })),
    [dashboard]);

  // ---------- Gráfico de BARRAS (últimos 6 meses) ----------
  const barras = useMemo(() => {
    const lista = (dashboard?.ultimos_6_meses || []).map((m) => ({ mes: m.mes, v: Number(m.valor) || 0 }));
    const b = buildBars(lista, { xLeft: 42, slot: 58, barW: 32, yTop: 14, yBase: 150, minH: 3 });
    if (!b) return { lista: [] };
    const gridLines = [0, 0.25, 0.5, 0.75, 1].map((f) => b.yTop + f * (b.yBase - b.yTop));
    const achatada = b.max === b.min;
    const gridLabels = achatada
      ? [{ y: b.yAt(0), label: fmtEURShort(0) }]
      : [0, 0.25, 0.5, 0.75, 1].map((f) => {
          const valor = b.min + f * (b.max - b.min);
          return { y: b.yAt(valor), label: fmtEURShort(valor) };
        });
    return { lista: b.bars, gridLines, gridLabels, yBase: b.yBase, width: b.width };
  }, [dashboard]);

  const cartoes = dashboard?.cartoes || {};
  // A hora a que a comparação MENSAL foi cortada — ver `dashboard.py`. As
  // linhas por loja não têm espaço para a frase inteira (que os cartões do
  // topo mostram), mas têm para a hora, e é ela que faz a diferença entre
  // «Anterior» e «Anterior até às 17:25».
  //
  // Só no mensal: «Ontem» passou a ser o dia anterior INTEIRO, por decisão do
  // dono — lá não há hora nenhuma a assinalar.
  const ateAsHoras = dashboard?.hora_de_corte
    ? ` até às ${dashboard.hora_de_corte}` : '';
  const porLoja = dashboard?.por_loja || [];
  const maisVendidos = dashboard?.mais_vendidos || [];
  const maisRentaveis = dashboard?.mais_rentaveis || [];
  // Quantos artigos vendidos hoje não têm preço de custo — é o que
  // transforma um cartão mudo numa frase que se pode resolver.
  const artigosSemCusto = dashboard?.artigos_sem_custo || 0;
  // Faturas de hoje cujo dinheiro está no cartão «Hoje» mas não se deixou
  // repartir por artigo. Quase sempre zero — e quando não for, diz-se, em
  // vez de deixar os dois números a discordar sem legenda.
  const porRepartir = dashboard?.documentos_por_repartir || 0;
  // Quantos artigos DIFERENTES se venderam hoje. É este — e não o
  // comprimento da lista da margem — que distingue "a loja ainda não
  // abriu" de "vendeu-se, mas não há margem para mostrar".
  const artigosVendidos = dashboard?.artigos_vendidos || 0;
  const semVendas = !!dashboard && !dashboard.ha_vendas;

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-dashboard-page">
      <PageHeader icon={LayoutDashboard} title="Dashboard" subtitle="Faturação · Gestão">
        <div className="flex items-center gap-2">
          {/* Sinal discreto de que há um pedido novo em curso — sem isto, ao
              mudar o interruptor com o dashboard já carregado, os números
              trocavam sem nenhum aviso de que tinham sido recarregados. */}
          {loading && dashboard && (
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground animate-spin" data-testid="fat-dashboard-a-actualizar" />
          )}
          <Switch id="fat-vat-toggle" checked={comIva} onCheckedChange={setComIva} data-testid="fat-vat-toggle" />
          <Label htmlFor="fat-vat-toggle" className="text-sm cursor-pointer whitespace-nowrap">Valores c/ IVA</Label>
        </div>
      </PageHeader>

      {/* Em que modo é que as lojas estão a emitir. Fica ANTES dos números:
          uma receita do dia lida por baixo de um POS em modo de testes é uma
          receita que não existe. */}
      <FatModoDeEmissao soQuandoImporta />

      {loading && !dashboard ? (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
        </div>
      ) : erro && !dashboard ? (
        <Card>
          <CardContent className="py-12 text-center space-y-3">
            <p className="text-muted-foreground text-sm">Não foi possível carregar o dashboard.</p>
            <Button variant="outline" onClick={load} data-testid="fat-dashboard-retry">
              <RefreshCw className="h-4 w-4 mr-2" />Tentar novamente
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Faixa "ainda sem vendas" — o ecrã continua completo por baixo,
              a zeros, à espera que o POS comece a faturar. */}
          {semVendas && (
            <Card className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30" data-testid="fat-dashboard-sem-vendas">
              <CardContent className="p-4 flex items-start gap-3">
                <div className="h-9 w-9 rounded-full bg-amber-100 dark:bg-amber-900/50 flex items-center justify-center shrink-0">
                  <Info className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <p className="text-sm font-medium text-amber-900 dark:text-amber-200">Ainda não há vendas registadas</p>
                  <p className="text-xs text-amber-800/80 dark:text-amber-300/80 mt-0.5">
                    Os números abaixo acendem sozinhos assim que o Ponto de Venda começar a faturar. A estrutura já está pronta à espera dos dados.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ---------- Cartão largo: 3 métricas + gráfico de área diário ---------- */}
          <Card>
            <CardContent className="p-0">
              <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-border">
                {CARTOES.map((k) => {
                  const cartao = cartoes[k.key] || {};
                  return (
                    <div key={k.key} className="p-5 sm:p-6 flex items-start gap-4" data-testid={`fat-cartao-${k.key}`}>
                      <div className="h-[72px] w-[72px] rounded-full bg-primary/10 dark:bg-primary/15 flex items-center justify-center shrink-0">
                        <k.icon className="h-8 w-8 text-primary" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-muted-foreground">
                          {k.prefixo} <span className="font-bold">{k.sufixo}</span>
                        </p>
                        <p className="text-[28px] sm:text-[30px] font-heading font-bold text-primary leading-tight mt-1">
                          {fmtEUR(cartao.valor)}
                        </p>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5">
                          <VariacaoPill variacao={cartao.variacao} />
                          <span className="text-xs text-muted-foreground">Anterior: {fmtEUR(cartao.valor_comparado)}</span>
                        </div>
                        {/* A frase que diz exactamente o que foi comparado com o
                            quê — é o que este dashboard tem e o do Vendus não
                            tem. Nunca escondida num tooltip. */}
                        {cartao.comparacao && (
                          <p className="text-xs text-muted-foreground mt-2 pt-2 border-t border-border"
                            data-testid={`fat-cartao-${k.key}-comparacao`}>
                            {cartao.comparacao}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="border-t border-border p-4 sm:p-5 space-y-3">
                <p className="text-sm font-semibold">
                  Faturação diária <span className="font-normal text-muted-foreground">· últimos 30 dias</span>
                </p>
                <GraficoDeArea
                  pontos={pontosDaArea}
                  testid="fat-dashboard-area"
                  ariaLabel="Faturação diária dos últimos 30 dias"
                />
              </div>
            </CardContent>
          </Card>

          {/* ---------- Mais Vendidos · Mais Rentáveis · Últimos 6 meses ---------- */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">
            <Card className="flex flex-col">
              <CardContent className="p-4 sm:p-5 flex flex-col flex-1" data-testid="fat-mais-vendidos">
                <div className="flex items-center gap-2">
                  <Rocket className="h-4 w-4 text-primary shrink-0" />
                  <p className="text-sm font-semibold">Mais Vendidos</p>
                  <span className="h-3.5 w-px bg-border" />
                  <span className="text-xs text-muted-foreground">Hoje</span>
                </div>
                <div className="flex-1 flex flex-col justify-center">
                  {maisVendidos.length === 0 ? (
                    <EmptyMini icon={PackageSearch} texto="Ainda não se vendeu nada hoje" />
                  ) : (
                    <TopoDeArtigos
                      itens={maisVendidos}
                      prefixo="fat-mais-vendido"
                      // O número que manda é a QUANTIDADE — é a pergunta deste
                      // cartão. O euro vem a seguir, mais apagado, porque a
                      // resposta a "o que é que mais sai?" não é em dinheiro.
                      principal={(a) => ({ valor: a.quantidade, texto: `${fmtQtd(a.quantidade)} un` })}
                      secundario={(a) => fmtEUR(a.valor)}
                    />
                  )}
                  {porRepartir > 0 ? (
                    <p className="text-xs text-muted-foreground mt-3" data-testid="fat-por-repartir">
                      {porRepartir === 1
                        ? '1 fatura de hoje não se deixou repartir por artigo — o valor dela está no cartão Hoje, mas não neste top.'
                        : `${porRepartir} faturas de hoje não se deixaram repartir por artigo — o valor delas está no cartão Hoje, mas não neste top.`}
                    </p>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card className="flex flex-col">
              <CardContent className="p-4 sm:p-5 flex flex-col flex-1" data-testid="fat-mais-rentaveis">
                <div className="flex items-center gap-2">
                  <Star className="h-4 w-4 text-primary shrink-0" />
                  <p className="text-sm font-semibold">Mais Rentáveis</p>
                  <span className="h-3.5 w-px bg-border" />
                  <span className="text-xs text-muted-foreground">Hoje</span>
                </div>
                <div className="flex-1 flex flex-col justify-center">
                  {maisRentaveis.length > 0 ? (
                    <>
                      <TopoDeArtigos
                        itens={maisRentaveis}
                        prefixo="fat-mais-rentavel"
                        principal={(a) => ({ valor: a.resultado, texto: fmtEUR(a.resultado) })}
                        // A percentagem diz o que o euro não diz: 5 € de
                        // margem em 9 € de vendas é outro negócio que 5 € em
                        // 90 €.
                        secundario={(a) => (a.margem_pct == null ? null
                          : `${a.margem_pct.toLocaleString('pt-PT', { maximumFractionDigits: 1 })}%`)}
                      />
                      {artigosSemCusto > 0 ? (
                        <p className="text-xs text-muted-foreground mt-3" data-testid="fat-rentaveis-em-falta">
                          {artigosSemCusto === 1
                            ? '1 artigo sem preço de custo ficou de fora.'
                            : `${artigosSemCusto} artigos sem preço de custo ficaram de fora.`}
                        </p>
                      ) : null}
                    </>
                  ) : artigosVendidos > 0 ? (
                    <SemMargem semCusto={artigosSemCusto} vendidos={artigosVendidos} />
                  ) : (
                    <EmptyMini icon={PackageSearch} texto="Ainda não se vendeu nada hoje" />
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="flex flex-col">
              <CardContent className="p-4 sm:p-5 flex flex-col flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <TrendingUp className="h-4 w-4 text-primary shrink-0" />
                  <p className="text-sm font-semibold">Últimos 6 meses</p>
                </div>
                <div className="flex-1 flex items-center">
                  {barras.lista.length === 0 ? (
                    <EmptyMini icon={BarChart3} />
                  ) : (
                    <div className="overflow-x-auto w-full">
                      {/* A largura mínima vive na moldura, e não no desenho: as
                          duas têm de ter a MESMA caixa, porque é dela que saem
                          as percentagens onde o balão assenta. */}
                      <div className="relative w-full"
                        style={{ minWidth: Math.max(260, barras.width) }}
                        onPointerLeave={() => setBarraTocada(null)}>
                      <svg viewBox={`0 0 ${barras.width} 190`} className="w-full"
                        xmlns="http://www.w3.org/2000/svg" data-testid="fat-dashboard-bars">
                        <defs>
                          <linearGradient id="fatBarsGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="1" />
                            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.55" />
                          </linearGradient>
                        </defs>
                        {barras.gridLines.map((y, i) => (
                          <line key={i} x1="38" y1={y} x2={barras.width - 6} y2={y} stroke="hsl(var(--border))" strokeWidth="1" />
                        ))}
                        {barras.gridLabels.map((g, i) => (
                          <text key={i} x="34" y={g.y + 3.5} textAnchor="end" fontSize="9" fill="hsl(var(--muted-foreground))">
                            {g.label}
                          </text>
                        ))}
                        {barras.lista.map((b, i) => (
                          <g key={i}>
                            <path
                              d={roundedBarPath(b.x, b.y, b.w, b.h, 5, b.neg ? 'bottom' : 'top')}
                              fill="url(#fatBarsGrad)"
                              data-testid={`fat-bar-${i}`}
                              data-em-foco={barraTocada === i ? 'sim' : 'nao'}
                              /* A barra apontada RESPONDE. Com seis barras
                                 encostadas, um balão sem nada aceso ao lado
                                 podia estar a falar de qualquer uma delas. */
                              stroke={barraTocada === i ? 'hsl(var(--primary))' : 'none'}
                              strokeWidth={barraTocada === i ? 1.5 : 0}
                              opacity={barraTocada == null || barraTocada === i ? 1 : 0.45}
                            />
                            <text x={b.cx} y={barras.yBase + 15} textAnchor="middle" fontSize="10" fill="hsl(var(--muted-foreground))">
                              {mesLabel(b.mes)}
                            </text>
                            {/* O alvo é a COLUNA inteira, não a barra pintada: a
                                barra de um mês fraco é uma tira fina e ninguém
                                lhe acerta. `fill="transparent"` e não `none` —
                                `none` não recebe o rato de todo. */}
                            <rect
                              x={b.cx - 29} y={0} width={58} height={190}
                              fill="transparent"
                              tabIndex={0}
                              role="img"
                              aria-label={`${mesLabel(b.mes)}: ${fmtEUR(b.v)}`}
                              data-testid={`fat-bar-toque-${i}`}
                              onPointerEnter={() => setBarraTocada(i)}
                              onFocus={() => setBarraTocada(i)}
                              onBlur={() => setBarraTocada(null)}
                            />
                          </g>
                        ))}
                      </svg>
                      {barraTocada != null && barras.lista[barraTocada] && (
                        <BalaoDoGrafico
                          testid="fat-bars-balao"
                          xPct={barras.lista[barraTocada].cx / barras.width}
                          yPct={barras.lista[barraTocada].y / 190}
                          valor={fmtEUR(barras.lista[barraTocada].v)}
                          etiqueta={mesLabel(barras.lista[barraTocada].mes)}
                        />
                      )}
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* ---------- Uma linha por loja ---------- */}
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3 flex-wrap px-1">
              <h2 className="font-heading font-semibold text-base">Por loja</h2>
              {(cartoes.hoje?.comparacao || cartoes.mensal?.comparacao) && (
                <p className="text-xs text-muted-foreground">
                  {`Hoje compara-se com o dia de ONTEM INTEIRO — a diferença fecha-se ao longo do dia${
                dashboard?.hora_de_corte
                  ? `. O Mensal compara com o mesmo pedaço do mês anterior, até às ${dashboard.hora_de_corte}`
                  : ''}.`}
                </p>
              )}
            </div>

            {porLoja.length === 0 ? (
              <Card>
                <CardContent className="py-8">
                  <p className="text-center text-muted-foreground text-sm">Sem lojas registadas.</p>
                </CardContent>
              </Card>
            ) : (
              porLoja.map((loja) => (
                <Card key={loja.loja_id} data-testid={`fat-loja-row-${loja.loja_id}`}>
                  <CardContent className="p-4 sm:p-5">
                    <div className="flex flex-col lg:flex-row lg:items-center gap-4">
                      <div className="flex items-center gap-2.5 min-w-0 lg:w-52 shrink-0">
                        <div className="h-9 w-9 rounded-lg bg-primary/10 dark:bg-primary/15 flex items-center justify-center shrink-0">
                          <Store className="h-4 w-4 text-primary" />
                        </div>
                        <span className="font-heading font-bold text-sm truncate">{loja.nome}</span>
                      </div>

                      <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-5 sm:gap-0 sm:divide-x sm:divide-border lg:border-l lg:border-border">
                        {/* Hoje */}
                        <div className="flex items-center justify-between gap-3 sm:pr-5 lg:pl-5">
                          <div className="min-w-0">
                            <p className="text-xs text-muted-foreground">Hoje</p>
                            <p className="text-xl font-heading font-bold text-primary leading-tight mt-0.5">
                              {fmtEUR(loja.hoje)}
                            </p>
                            <div className="flex flex-wrap items-center gap-1.5 mt-1">
                              <VariacaoPill variacao={loja.variacao_hoje} />
                              <span className="text-xs text-muted-foreground">
                                Ontem: {fmtEUR(loja.hoje_anterior)}
                              </span>
                            </div>
                          </div>
                          <MiniArea
                            /* A data viaja com o valor: sem ela o balão não tinha o que dizer. */
                            pontos={(loja.serie_diaria || []).map(
                              (p) => ({ data: p.data, v: Number(p.valor) || 0 }))}
                            gradId={`fatLojaGradHoje-${loja.loja_id}`}
                          />
                        </div>

                        {/* Mensal */}
                        <div className="flex items-center justify-between gap-3 sm:pl-5">
                          <div className="min-w-0">
                            <p className="text-xs text-muted-foreground">Mensal</p>
                            <p className="text-xl font-heading font-bold text-primary leading-tight mt-0.5">
                              {fmtEUR(loja.mensal)}
                            </p>
                            <div className="flex flex-wrap items-center gap-1.5 mt-1">
                              <VariacaoPill variacao={loja.variacao_mensal} />
                              <span className="text-xs text-muted-foreground">
                                Anterior{ateAsHoras}: {fmtEUR(loja.mensal_anterior)}
                              </span>
                            </div>
                          </div>
                          <MiniBars pontos={(loja.serie_mensal || []).map(
                            (p) => ({ mes: p.mes, v: Number(p.valor) || 0 }))} />
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
