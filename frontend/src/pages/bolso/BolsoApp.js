import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Loader2, LogOut, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { euros, getPainel, percentagem, quandoFoi, TIMEOUT_MS } from '@/lib/bolso';

// **Gestão Lisbonb** — a faturação do grupo no telemóvel do gestor.
//
// (No código chama-se "bolso" — a rota, a pasta, o `lib/bolso.js`. Foi o nome
// de trabalho e ficou; o que o dono vê é "Gestão Lisbonb", que é o nome do
// portal e o da app no telemóvel dele.)
//
// A forma é a do painel do Vendus que o dono já usa e conhece (números
// grandes, medalha com a percentagem, o valor de comparação ao lado, e as
// lojas em separadores no fundo). **A aritmética não é.**
//
// ## Onde este ecrã diverge do que ele conhece, e porquê
//
// O painel do Vendus mostra, a 6 de Setembro, "Faturação Mensal −77,52%, Mês
// Anterior: 44.421,91 €". Está a comparar **seis dias de Setembro com Agosto
// INTEIRO** — e o mesmo no cartão anual, 2026 até hoje contra 2025 completo,
// "−21,31%". Não é uma queda: é meio mês a ser medido contra um mês cheio, e
// aparece a vermelho todos os dias até ao dia 28.
//
// Aqui a comparação é sempre com o **período equivalente** e o rótulo diz o
// que foi comparado com o quê. É por isso que os números deste ecrã **não vão
// bater** com os do painel do Vendus — e é de propósito.
//
// ## Isto corre dentro de uma app iOS, e o ecrã sabe disso
//
// A casca (`app-bolso/`) carrega esta página numa WebView. Três consequências
// que mandam no desenho:
//
//   1. **A página pinta até às bordas do ecrã** (`contentInset: never` na
//      casca): o cabeçalho e a barra de baixo usam os utilitários de área
//      segura do `index.css` — os MESMOS que o resto do portal — para não
//      ficarem por baixo da Dynamic Island nem da barra de gestos.
//   2. **O título grande encolhe ao rolar**, como nas apps do sistema. É o
//      detalhe que mais separa "app" de "site dentro de uma janela".
//   3. **Nada de `backdrop-filter`.** Num elemento fixo, é dos efeitos mais
//      caros da WebView e foi a causa medida dos solavancos que o dono sentiu.
//      O fundo é sólido.
//
// ## O âmbito, a três níveis
//
// Grupo → Empresa → Loja, na barra de baixo, ao alcance do polegar. A escolha
// sobrevive a fechar a app: um telemóvel deita a página fora quando vai para
// o bolso, e voltar a escolher a loja de cada vez era o que fazia a app não
// ser aberta.

const NOME_DA_ORIGEM = {
  faturacao: 'O nosso POS',
  vendus: 'Vendus',
  moloni: 'Moloni',
};

const CHAVE_EMPRESA = 'bolso_empresa';
const CHAVE_UNIDADE = 'bolso_unidade';
const CHAVE_IVA = 'bolso_com_iva';

const ler = (chave, omissao) => {
  try { return localStorage.getItem(chave) ?? omissao; } catch (e) { return omissao; }
};
const guardar = (chave, valor) => {
  try {
    if (valor === null) localStorage.removeItem(chave);
    else localStorage.setItem(chave, valor);
  } catch (e) { /* modo privado */ }
};

// O manifesto do portal aponta para o POS (`start_url: /faturacao/pos`). Sem
// esta troca, "Adicionar ao Ecrã Principal" a partir daqui instalava um ícone
// que **abre o balcão da loja** — o manifesto é que manda, não o endereço que
// está à frente.
function useManifestoDoBolso() {
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

// O título grande encolhe para o cabeçalho ao rolar, como nas apps do sistema.
// Um limiar e um estado booleano, e não a posição do scroll: assim o React
// volta a desenhar UMA vez, quando se atravessa a linha, e não a cada pixel —
// que era a diferença entre deslizar e arrastar.
function useRolouAlem(limiar = 44) {
  const [rolou, setRolou] = useState(false);
  const rolouRef = useRef(false);
  useEffect(() => {
    const aoRolar = () => {
      const passou = window.scrollY > limiar;
      if (passou !== rolouRef.current) {
        rolouRef.current = passou;
        setRolou(passou);
      }
    };
    aoRolar();
    window.addEventListener('scroll', aoRolar, { passive: true });
    return () => window.removeEventListener('scroll', aoRolar);
  }, [limiar]);
  return rolou;
}

// --- Peças -------------------------------------------------------------------

// O lugar de um número que ainda não chegou. **Não é decoração**: sem isto, ao
// trocar de empresa ficavam à vista os números da EMPRESA ANTERIOR por baixo
// do separador novo — o ecrã afirmava uma coisa falsa durante o tempo do
// pedido. Um traço a pulsar não afirma nada.
function Esqueleto({ className = '' }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block rounded-md bg-muted-foreground/15 motion-safe:animate-pulse ${className}`}
    />
  );
}

// A medalha do painel do Vendus: verde a subir, vermelha a descer. Só aparece
// quando há mesmo uma percentagem — sem período anterior não se pinta nada,
// porque uma medalha a dizer "0%" seria uma afirmação que ninguém mediu.
function Medalha({ variacao }) {
  const texto = percentagem(variacao);
  if (texto === null) return null;
  const subiu = Number(variacao) >= 0;
  return (
    <span className={`shrink-0 rounded-lg px-2 py-1 text-sm font-bold tabular-nums ${
      subiu ? 'bg-success-strong text-white' : 'bg-destructive-strong text-white'
    }`}>
      {texto}
    </span>
  );
}

// A do cartão de hoje é outra coisa e por isso tem outra cor: não é um
// julgamento (subiu/desceu), é um ponteiro — quanto do dia de ontem já foi
// feito. Pintá-la de vermelho às nove da manhã era exactamente o alarme falso
// que este ecrã existe para não dar.
function MedalhaDeProgresso({ progresso }) {
  if (progresso === null || progresso === undefined) return null;
  return (
    // `accent` + `accent-foreground` é o par que o sistema já tem para texto
    // sobre um fundo tingido — e é o par que passa o contraste nos dois temas.
    // `bg-primary/10` com `text-primary` ficava em 4,4:1, abaixo do mínimo.
    <span className="shrink-0 rounded-lg bg-accent text-accent-foreground px-2 py-1 text-sm font-bold tabular-nums">
      {Math.round(progresso)}% de ontem
    </span>
  );
}

function CartaoGrande({ titulo, dados, comIva, aCarregar, atraso = 0 }) {
  const valor = dados ? (comIva ? dados.valor : dados.valor_sem_iva) : null;
  const rotulo = dados?.anterior_rotulo;
  return (
    <section
      className="rounded-2xl border bg-card overflow-hidden animate-fade-in"
      style={{ animationDelay: `${atraso}ms` }}
    >
      <div className="px-5 pt-4 pb-5">
        <h2 className="font-heading font-bold text-lg">{titulo}</h2>
        {/* `whitespace-nowrap` não é decoração: `€ 384 210,55` a este tamanho
            parte o símbolo para uma linha e o número para outra, e um valor em
            dinheiro partido ao meio lê-se mal e mede-se pior. */}
        {aCarregar ? (
          <Esqueleto className="h-11 w-56 mt-3 align-bottom" />
        ) : (
          <p className="font-heading font-bold text-primary tabular-nums whitespace-nowrap text-4xl sm:text-5xl leading-none mt-3 tracking-tight">
            {euros(valor)}
          </p>
        )}
        {!aCarregar && !comIva && dados?.valor_sem_iva === null && (
          <p className="text-xs text-warning-strong mt-2">
            Uma das origens não diz o valor sem IVA neste período.
          </p>
        )}
      </div>

      <div className="border-t bg-muted/50 px-5 py-3 flex items-center gap-2.5 flex-wrap min-h-[3.25rem]">
        {aCarregar ? (
          <Esqueleto className="h-4 w-48" />
        ) : (
          <>
            <Medalha variacao={dados?.variacao} />
            <MedalhaDeProgresso progresso={dados?.progresso} />
            <span className="text-sm text-muted-foreground min-w-0">
              {dados?.anterior !== null && dados?.anterior !== undefined ? (
                <>
                  <span className="font-medium text-foreground">{rotulo}:</span>{' '}
                  <span className="tabular-nums">{euros(dados.anterior)}</span>
                </>
              ) : (
                dados?.nota || 'sem período anterior para comparar'
              )}
            </span>
          </>
        )}
      </div>

      {/* **A linha que separa este painel do outro.** O do Vendus escreve "Mês
          Anterior: 44.421,91 €" — e não diz que esse valor é o mês INTEIRO
          enquanto o de cima são seis dias. Aqui diz-se o que foi medido de
          cada lado, e a percentagem deixa de poder enganar. */}
      {!aCarregar && dados?.actual_rotulo && (
        <p className="px-5 pb-3 text-xs text-muted-foreground">
          Compara {dados.actual_rotulo} — os dias já fechados.
        </p>
      )}
    </section>
  );
}

// Lista agrupada, como as dos ecrãs de definições do iOS: uma barra fina por
// linha a dar a proporção sem precisar de um gráfico. A barra é um `div` com
// largura em percentagem — não é uma animação de layout, é a largura final
// desenhada uma vez.
function PorLoja({ itens, por, comIva, aCarregar }) {
  if (aCarregar) {
    return (
      <section className="rounded-2xl border bg-card overflow-hidden px-5 py-4 space-y-3">
        <Esqueleto className="h-5 w-40" />
        {[0, 1, 2].map((i) => <Esqueleto key={i} className="h-4 w-full" />)}
      </section>
    );
  }
  if (!itens || itens.length === 0) return null;
  const total = itens.reduce((s, i) => s + (i.valor || 0), 0);
  return (
    <section className="rounded-2xl border bg-card overflow-hidden animate-fade-in">
      <h2 className="font-heading font-bold text-lg px-5 pt-4">Este mês, por {por}</h2>
      <ul className="mt-3 divide-y">
        {itens.map((i) => {
          const parte = total > 0 ? (i.valor / total) * 100 : 0;
          return (
            <li key={i.id || 'sem'} className="px-5 py-3">
              <div className="flex items-baseline gap-3">
                <span className="min-w-0 flex-1 truncate">{i.nome}</span>
                <span className="font-heading font-bold tabular-nums shrink-0">
                  {euros(i.valor)}
                </span>
                <span className="text-xs text-muted-foreground tabular-nums w-9 text-right shrink-0">
                  {total > 0 ? `${Math.round(parte)}%` : '—'}
                </span>
              </div>
              <div className="mt-2 h-1 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary/70"
                  style={{ width: `${Math.max(parte, 1)}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      {!comIva && (
        <p className="px-5 pb-3 pt-1 text-[11px] text-muted-foreground">
          A repartição mostra-se sempre com IVA.
        </p>
      )}
    </section>
  );
}

// Linha dos últimos 30 dias, em SVG puro — trinta pontos não justificam uma
// biblioteca de gráficos no telemóvel. A área por baixo dá corpo à linha sem
// pedir uma legenda.
function Linha30Dias({ pontos, aCarregar }) {
  if (aCarregar) {
    return (
      <section className="rounded-2xl border bg-card px-5 py-4 space-y-3">
        <Esqueleto className="h-5 w-36" />
        <Esqueleto className="h-20 w-full" />
      </section>
    );
  }
  if (!pontos || pontos.length === 0) return null;
  const maximo = Math.max(...pontos.map((p) => p.valor), 1);
  const L = 300;
  const A = 64;
  const passo = pontos.length > 1 ? L / (pontos.length - 1) : L;
  const xy = pontos.map((p, i) => [i * passo, A - (p.valor / maximo) * A]);
  const linha = xy.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const area = `${linha} L ${L} ${A} L 0 ${A} Z`;
  return (
    <section className="rounded-2xl border bg-card p-5 animate-fade-in">
      <h2 className="font-heading font-bold text-lg">Últimos 30 dias</h2>
      <svg viewBox={`0 0 ${L} ${A}`} className="w-full h-20 mt-3" preserveAspectRatio="none"
           role="img" aria-label={`Faturação dos últimos ${pontos.length} dias`}>
        <defs>
          <linearGradient id="bolso-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.22" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#bolso-area)" className="text-primary" />
        <path d={linha} fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinejoin="round" className="text-primary" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between text-[11px] text-muted-foreground tabular-nums mt-1">
        <span>{pontos[0].dia.slice(8)}/{pontos[0].dia.slice(5, 7)}</span>
        <span>máx. {euros(maximo)}</span>
        <span>{pontos[pontos.length - 1].dia.slice(8)}/{pontos[pontos.length - 1].dia.slice(5, 7)}</span>
      </div>
    </section>
  );
}

// A barra de baixo — o âmbito ao alcance do polegar, como os separadores do
// painel que o dono já usa. Duas filas, e a segunda só existe quando a empresa
// escolhida tem lojas: uma fila vazia a ocupar espaço é pior do que não haver
// fila. Alvos de 44px, que é o mínimo do iOS para o dedo.
function BarraDeAmbito({ empresas, empresaActiva, onEmpresa, unidades, unidadeActiva, onUnidade }) {
  const Separador = ({ activo, onClick, children }) => (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={activo}
      className={`shrink-0 h-12 px-4 text-sm font-semibold uppercase tracking-wide whitespace-nowrap
        border-b-2 transition-colors duration-200 active:bg-accent/60
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${
        activo ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'
      }`}
    >
      {children}
    </button>
  );

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-30 bg-card border-t safe-area-inset-bottom">
      {unidades.length > 0 && (
        <div className="flex overflow-x-auto border-b bg-muted/40">
          <Separador activo={!unidadeActiva} onClick={() => onUnidade(null)}>
            Todas as lojas
          </Separador>
          {unidades.map((u) => (
            <Separador key={u.id} activo={unidadeActiva === u.id} onClick={() => onUnidade(u.id)}>
              {u.nome}
            </Separador>
          ))}
        </div>
      )}
      <div className="flex overflow-x-auto">
        <Separador activo={empresaActiva === 'all'} onClick={() => onEmpresa('all')}>
          Todos
        </Separador>
        {empresas.map((c) => (
          <Separador key={c.id} activo={empresaActiva === c.id} onClick={() => onEmpresa(c.id)}>
            {c.nome}
          </Separador>
        ))}
      </div>
    </nav>
  );
}

// --- O ecrã ------------------------------------------------------------------

export default function BolsoApp() {
  useManifestoDoBolso();
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const rolou = useRolouAlem();

  const [empresa, setEmpresa] = useState(() => ler(CHAVE_EMPRESA, 'all'));
  const [unidade, setUnidade] = useState(() => ler(CHAVE_UNIDADE, null) || null);
  const [comIva, setComIva] = useState(() => ler(CHAVE_IVA, '1') !== '0');
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [lidoAs, setLidoAs] = useState(null);

  const carregar = useCallback(async (alvoEmpresa, alvoUnidade) => {
    setCarregando(true);
    setErro(null);
    try {
      const { data } = await getPainel(alvoEmpresa, alvoUnidade);
      setDados(data);
      setLidoAs(new Date().toISOString());
    } catch (e) {
      const status = e?.response?.status;
      if (status === 401) { logout(); navigate('/login'); return; }
      // Sem resposta não se aprendeu nada, e o que está no ecrã continua a
      // valer — com o carimbo antigo à vista. Apagá-lo era trocar informação
      // velha, mas datada, por nenhuma.
      setErro(
        e?.response
          ? (e.response.data?.detail || 'O servidor recusou este pedido.')
          : `Sem resposta do servidor em ${Math.round(TIMEOUT_MS / 1000)} segundos.`
      );
    } finally {
      setCarregando(false);
    }
  }, [logout, navigate]);

  useEffect(() => { carregar(empresa, unidade); }, [empresa, unidade, carregar]);

  // Numa app instalada, voltar ao ecrã não remonta a página: sem isto, o dono
  // abria o ícone às 13h e via os números da manhã com um carimbo credível.
  useEffect(() => {
    const aoVoltar = () => { if (!document.hidden) carregar(empresa, unidade); };
    document.addEventListener('visibilitychange', aoVoltar);
    return () => document.removeEventListener('visibilitychange', aoVoltar);
  }, [empresa, unidade, carregar]);

  // Mudar de empresa larga a loja: um id de loja da empresa anterior não
  // existe nesta, e o servidor recusa-o com 404. Limpar aqui é o que faz o
  // toque seguinte funcionar sem uma mensagem de erro pelo meio.
  const escolherEmpresa = (id) => {
    setEmpresa(id); guardar(CHAVE_EMPRESA, id);
    setUnidade(null); guardar(CHAVE_UNIDADE, null);
  };
  const escolherUnidade = (id) => { setUnidade(id); guardar(CHAVE_UNIDADE, id); };
  const alternarIva = () => {
    setComIva((v) => { guardar(CHAVE_IVA, v ? '0' : '1'); return !v; });
  };

  const ambito = dados?.ambito;
  const cartoes = dados?.cartoes || {};
  const unidades = ambito?.unidades || [];

  // **Os números que estão no ecrã são DESTE âmbito?** O servidor devolve o
  // âmbito que somou, e é com ele que se compara — não com o que se pediu.
  // Enquanto não baterem, mostram-se esqueletos: sem isto, tocar em "Purple
  // House" deixava os números da Fordaimon à vista, por baixo do separador
  // novo, durante o tempo do pedido. O ecrã afirmava uma coisa falsa.
  const desteAmbito = !!dados
    && ambito?.pedido === empresa
    && (ambito?.unidade || null) === (unidade || null);
  const aCarregarNumeros = !desteAmbito;

  const nomeDoAmbito = unidade
    ? (unidades.find((u) => u.id === unidade)?.nome || 'Loja')
    : (empresa === 'all'
        ? 'Todas as empresas'
        : (ambito?.somadas || []).find((c) => c.id === empresa)?.nome || '');

  return (
    <div className="min-h-[100dvh] bg-muted/30 pb-40">
      {/* Cabeçalho fixo. **Sem `backdrop-filter`**: num elemento fixo é dos
          efeitos mais caros da WebView do iPhone, e foi a causa medida dos
          solavancos. O título só aparece aqui depois de o grande sair do ecrã,
          como nas apps do sistema. */}
      <header className="sticky top-0 z-20 bg-card border-b safe-area-inset-top">
        <div className="flex items-center gap-1 px-3 h-14">
          <div className="min-w-0 flex-1">
            <p className={`font-heading font-bold text-base leading-none truncate transition-opacity duration-200 ${
              rolou ? 'opacity-100' : 'opacity-0'
            }`}>
              {nomeDoAmbito}
            </p>
          </div>

          {/* O interruptor do IVA diz o que MOSTRA, não o que faria se lhe
              tocassem — é a leitura que a etiqueta tem de suportar quando se
              olha para o número ao lado. */}
          <Button
            variant={comIva ? 'ghost' : 'secondary'}
            className="h-11 px-3 text-xs font-semibold tabular-nums"
            onClick={alternarIva}
            aria-pressed={!comIva}
            title={comIva ? 'A mostrar com IVA. Tocar para ver sem IVA.' : 'A mostrar sem IVA. Tocar para ver com IVA.'}
          >
            {comIva ? 'c/IVA' : 's/IVA'}
          </Button>
          <Button variant="ghost" size="icon" className="h-11 w-11"
                  onClick={() => carregar(empresa, unidade)} disabled={carregando}
                  aria-label="Voltar a ler">
            {carregando
              ? <Loader2 className="h-5 w-5 animate-spin" />
              : <RefreshCw className="h-5 w-5" />}
          </Button>
          <Button variant="ghost" size="icon" className="h-11 w-11"
                  onClick={() => { logout(); navigate('/login'); }} aria-label="Terminar sessão">
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </header>

      <main className="px-3 pt-2 pb-6 space-y-3 max-w-2xl mx-auto">
        {/* O título grande, que o cabeçalho recolhe ao rolar. */}
        <div className="px-2 pt-1 pb-1">
          <h1 className="font-heading font-bold text-3xl leading-tight">{nomeDoAmbito}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {lidoAs ? `Lido ${quandoFoi(lidoAs)}` : 'A ler…'}
            {user?.name ? ` · ${user.name}` : ''}
          </p>
        </div>

        {erro && (
          <section className="rounded-2xl border border-destructive/40 bg-destructive/10 p-4 flex items-start gap-2.5">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="font-medium">Não foi possível ler agora.</p>
              <p className="text-sm text-muted-foreground mt-0.5 break-words">{erro}</p>
              {dados && (
                <p className="text-sm text-muted-foreground mt-1">
                  O que está em baixo é a leitura anterior.
                </p>
              )}
            </div>
          </section>
        )}

        {(ambito?.sem_acesso || []).length > 0 && empresa === 'all' && (
          <section className="rounded-2xl border border-warning/40 bg-warning/10 p-3 flex items-start gap-2.5">
            <AlertTriangle className="h-4 w-4 text-warning-strong shrink-0 mt-0.5" />
            <p className="text-sm min-w-0">
              Sem acesso a: <strong>{ambito.sem_acesso.join(', ')}</strong>. Estes números não
              incluem essa faturação.
            </p>
          </section>
        )}

        <CartaoGrande titulo="Faturação Hoje" dados={cartoes.hoje} comIva={comIva}
                      aCarregar={aCarregarNumeros} atraso={0} />
        <CartaoGrande titulo="Faturação Mensal" dados={cartoes.mes} comIva={comIva}
                      aCarregar={aCarregarNumeros} atraso={40} />
        <CartaoGrande titulo="Faturação Anual" dados={cartoes.ano} comIva={comIva}
                      aCarregar={aCarregarNumeros} atraso={80} />

        <PorLoja itens={dados?.reparticao} por={dados?.reparticao_por}
                 comIva={comIva} aCarregar={aCarregarNumeros} />
        <Linha30Dias pontos={dados?.serie_dias} aCarregar={aCarregarNumeros} />

        {desteAmbito && (dados.dias_sem_vendas || []).length > 0 && (
          <section className="rounded-2xl border bg-card p-4">
            <p className="text-sm">
              <strong>Sem vendas registadas</strong> em{' '}
              {dados.dias_sem_vendas.map((d) => `${d.slice(8)}/${d.slice(5, 7)}`).join(', ')}.
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Pode ser um dia fechado — ou uma leitura que não correu.
            </p>
          </section>
        )}

        {desteAmbito && (
          <section className="rounded-2xl border bg-card p-4 space-y-1">
            <h2 className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
              Origem dos números
            </h2>
            {(dados.leituras || []).map((l) => (
              <p key={l.origem} className="text-xs text-muted-foreground">
                <span className="text-foreground">{NOME_DA_ORIGEM[l.origem] || l.origem}</span>
                {' · '}lido {quandoFoi(l.terminou_em) || 'em data desconhecida'}
                {l.completa === false && <span className="text-warning-strong"> · com queixas</span>}
              </p>
            ))}
            {(ambito?.somadas || []).length > 0 && (
              <p className="text-xs text-muted-foreground pt-1">
                A somar: {ambito.somadas.map((c) => c.nome).join(' · ')}
              </p>
            )}
          </section>
        )}
      </main>

      <BarraDeAmbito
        empresas={ambito?.somadas || []}
        empresaActiva={empresa}
        onEmpresa={escolherEmpresa}
        unidades={unidades}
        unidadeActiva={unidade}
        onUnidade={escolherUnidade}
      />
    </div>
  );
}
