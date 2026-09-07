import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ChevronRight, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { euros, getPainel, percentagem, quandoFoi, TIMEOUT_MS } from '@/lib/bolso';

// **Gestão Lisbonb** — a faturação do grupo no telemóvel do gestor.
//
// (No código chama-se "bolso" — a rota, a pasta, o `lib/bolso.js`. Foi o nome
// de trabalho e ficou; o que o dono vê é "Gestão Lisbonb", que é o nome do
// portal e o da app no telemóvel dele.)
//
// A gramática é a do painel do Vendus que o dono já usa (número grande,
// medalha com a percentagem, valor de comparação ao lado, âmbito em
// separadores no fundo). **A aritmética não é.**
//
// ## Onde este ecrã diverge do que ele conhece, e porquê
//
// O painel do Vendus mostra, a 6 de Setembro, "Faturação Mensal −77,52%, Mês
// Anterior: 44.421,91 €". Está a comparar **seis dias de Setembro com Agosto
// INTEIRO** — e o mesmo no cartão anual, 2026 até hoje contra 2025 completo.
// Não é uma queda: é meio mês medido contra um mês cheio, e aparece a vermelho
// todos os dias até ao dia 28.
//
// Aqui a comparação é sempre com o **período equivalente** e o rótulo diz o
// que foi comparado com o quê. É por isso que os números deste ecrã **não vão
// bater** com os do painel do Vendus — e é de propósito.
//
// ## A forma: um número manda, os outros servem
//
// Três cartões iguais empilhados davam uma página de 1822px para responder a
// três perguntas — o ano custava duas rolagens. Hoje é o herói (sem cartão
// nenhum à volta, porque o que não tem moldura não precisa de competir), e o
// mês e o ano são duas linhas de uma lista. A hierarquia passou a ser feita
// por tamanho e por espaço, não por caixas.
//
// ## Isto corre dentro de uma app iOS, e o ecrã sabe disso
//
//   1. **A página pinta até às bordas** (`contentInset: never` na casca): o
//      cabeçalho e a barra usam os utilitários de área segura do `index.css`.
//   2. **Nada de `backdrop-filter`.** Num elemento fixo é dos efeitos mais
//      caros da WebView e foi a causa medida dos solavancos. O fundo é sólido.
//   3. **Nada de transições de opacidade no cabeçalho.** O nome do âmbito está
//      lá desde o primeiro pixel: saber o que se está a ver não pode depender
//      de se ter rolado.
//
// ## O âmbito, a três níveis
//
// Grupo → Empresa → Loja, no fundo, ao alcance do polegar. A escolha sobrevive
// a fechar a app: um telemóvel deita a página fora quando vai para o bolso, e
// voltar a escolher a loja de cada vez era o que fazia a app não ser aberta.

const NOME_DA_ORIGEM = {
  faturacao: 'O nosso POS',
  vendus: 'Vendus',
  moloni: 'Moloni',
};

const CHAVE_EMPRESA = 'bolso_empresa';
const CHAVE_UNIDADE = 'bolso_unidade';
const CHAVE_IVA = 'bolso_com_iva';
const CHAVE_EMPRESAS = 'bolso_empresas';

const ler = (chave, omissao) => {
  try { return localStorage.getItem(chave) ?? omissao; } catch (e) { return omissao; }
};
const guardar = (chave, valor) => {
  try {
    if (valor === null) localStorage.removeItem(chave);
    else localStorage.setItem(chave, valor);
  } catch (e) { /* modo privado */ }
};

// **A lista das empresas tem de ser guardada, e não é uma optimização.**
//
// O servidor devolve em `ambito.somadas` as empresas que SOMOU — logo, com uma
// empresa escolhida devolve uma só (`ids_no_ambito`, em `server.py`). A barra
// alimentava-se dessa lista, e o resultado era este, medido no browser:
//
//     no grupo:            [Todos] [Fordaimon] [Purple House] [Lenha e Brasa]
//     dentro da Fordaimon: [Todos] [Fordaimon]
//
// Ir da Fordaimon para a Purple House obrigava a passar por "Todos". Guardar a
// última lista completa que se viu resolve isso e sobrevive a fechar a app —
// que é o caso que interessa, porque o arranque pode ser já dentro de uma
// empresa.
const lerEmpresas = () => {
  try { return JSON.parse(localStorage.getItem(CHAVE_EMPRESAS) || '[]'); } catch (e) { return []; }
};

// O rótulo do segmento é a primeira palavra: "Fordaimon", "Purple", "Lenha".
// Quatro segmentos em 375px dão ~83px cada, e o nome inteiro só cabia com
// reticências — que foi metade do que estava mal na barra antiga. O nome
// completo está sempre no cabeçalho, por cima.
// ponytail: a primeira palavra chega para estas três; se duas colidirem, passa
// a nome completo com truncate.
const primeiraPalavra = (nome) => (nome || '').trim().split(/\s+/)[0] || nome;

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

// --- Peças -------------------------------------------------------------------

// O lugar de um número que ainda não chegou. **Não é decoração**: sem isto, ao
// trocar de empresa ficavam à vista os números da EMPRESA ANTERIOR por baixo
// do rótulo novo — o ecrã afirmava uma coisa falsa durante o tempo do pedido.
// Um traço a pulsar não afirma nada.
function Esqueleto({ className = '' }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block rounded-md bg-muted-foreground/15 motion-safe:animate-pulse ${className}`}
    />
  );
}

// **O símbolo do euro deixa de disputar espaço com os dígitos.** Desenhado do
// mesmo tamanho e peso, roubava largura ao número — que é a única coisa que se
// vem ver. Metade da altura e a cor do texto secundário: continua a ler-se,
// deixa de competir.
//
// Só serve o herói. Aos 17px das linhas, metade dá 8,5px e não vale a pena.
function ValorGrande({ valor, className = '' }) {
  const s = euros(valor);
  // O `euros()` devolve "—" quando o servidor não soube dizer (nunca 0,00 €).
  if (!s.startsWith('€ ')) return <span className={className}>{s}</span>;
  return (
    <span className={`whitespace-nowrap ${className}`}>
      <span className="text-[0.5em] font-semibold text-muted-foreground align-baseline mr-[0.14em]">€</span>
      {s.slice(2)}
    </span>
  );
}

// A medalha do painel do Vendus: verde a subir, vermelha a descer. Só aparece
// quando há mesmo uma percentagem — sem período anterior não se pinta nada,
// porque uma medalha a dizer "0%" seria uma afirmação que ninguém mediu.
//
// **É a única pastilha do ecrã, e significa uma coisa só.** Antes havia duas
// geometrias e duas linguagens de cor para a mesma ideia (uma verde sólida, uma
// azul pálida) e liam-se como coisas diferentes.
function Medalha({ variacao }) {
  const texto = percentagem(variacao);
  if (texto === null) return null;
  return (
    <span className={`inline-flex items-center h-6 shrink-0 rounded-full px-2 text-[13px] font-semibold tabular-nums ${
      Number(variacao) >= 0 ? 'bg-success-strong text-white' : 'bg-destructive-strong text-white'
    }`}>
      {texto}
    </span>
  );
}

// O progresso do dia não é um julgamento (subiu/desceu) — é um ponteiro. Uma
// régua diz isso sem pedir cor semântica nenhuma: pintar de vermelho às nove da
// manhã era exactamente o alarme falso que este ecrã existe para não dar.
function Regua({ progresso }) {
  if (progresso === null || progresso === undefined) return null;
  return (
    <div className="mt-3 h-1.5 rounded-full bg-muted overflow-hidden">
      {/* A largura trava nos 100%; o número da legenda NÃO trava — 118% é boa
          notícia e uma régua a rebentar a caixa não a dava melhor. */}
      <div
        className={`h-full rounded-full ${progresso >= 100 ? 'bg-success-strong' : 'bg-primary'}`}
        style={{ width: `${Math.min(progresso, 100)}%` }}
      />
    </div>
  );
}

// Uma linha da lista mês/ano. Os três estados nulos que ela TEM de aguentar —
// e dois deles acontecem todos os dias:
//
//   1. `anterior` nulo COM `nota` → é o Ano, porque o sistema começou em 2026 e
//      não há 2025 com que comparar. Escreve-se a nota, sem medalha.
//   2. `anterior` nulo SEM `nota` → é o dia 1 de cada mês, em que o mês
//      anterior equivalente ainda não tem um único dia fechado.
//   3. `valor_sem_iva` nulo em modo s/IVA → o valor sai "—" e a razão fica
//      NESTA linha; sem isso ficava um travessão órfão sem se saber de quê.
function LinhaPeriodo({ rotulo, dados, comIva, aCarregar }) {
  const valor = dados ? (comIva ? dados.valor : dados.valor_sem_iva) : null;
  const semIva = !comIva && dados?.valor_sem_iva === null;
  const temComparacao = dados?.anterior !== null && dados?.anterior !== undefined;
  return (
    <div className="px-4 py-3.5 flex items-start justify-between gap-3 min-h-[4rem]">
      <div className="min-w-0 flex-1">
        <p className="text-[16px] font-semibold leading-tight">{rotulo}</p>
        <p className={`mt-1 text-[12px] leading-snug ${semIva ? 'text-warning-strong' : 'text-muted-foreground'}`}>
          {semIva
            ? 'sem valor sem IVA neste período'
            : temComparacao
              ? <>vs. {dados.anterior_rotulo}: <span className="tabular-nums">{euros(dados.anterior)}</span></>
              : (dados?.nota || 'sem período anterior para comparar')}
        </p>
      </div>
      <div className="shrink-0 text-right">
        {aCarregar
          ? <Esqueleto className="h-5 w-24" />
          : (
            <p className="font-heading font-bold text-[17px] leading-tight tabular-nums whitespace-nowrap">
              {euros(valor)}
            </p>
          )}
        {/* A medalha é sobre o valor COM IVA. Ao lado de um "—" não se lê. */}
        {!aCarregar && !semIva && (
          <div className="mt-1 flex justify-end"><Medalha variacao={dados?.variacao} /></div>
        )}
      </div>
    </div>
  );
}

// Lista agrupada, como as dos ecrãs de definições do iOS: uma barra fina por
// linha a dar a proporção sem precisar de um gráfico.
//
// **E é a segunda porta da navegação.** Ver que Alfragide fez 4 210 € e ter de
// ir ao fundo do ecrã escolher Alfragide na barra era um caminho que ninguém
// faz duas vezes. A linha leva lá.
function PorLoja({ itens, por, comIva, aCarregar, podeEscolher, onEscolher }) {
  if (aCarregar) {
    return (
      <section className="rounded-2xl border bg-card overflow-hidden px-4 py-4 space-y-3">
        <Esqueleto className="h-5 w-40" />
        {[0, 1, 2].map((i) => <Esqueleto key={i} className="h-4 w-full" />)}
      </section>
    );
  }
  if (!itens || itens.length === 0) return null;
  const total = itens.reduce((s, i) => s + (i.valor || 0), 0);

  const Conteudo = ({ i, parte }) => (
    <>
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 truncate text-left">{i.nome}</span>
        <span className="font-heading font-bold tabular-nums shrink-0">{euros(i.valor)}</span>
        <span className="text-xs text-muted-foreground tabular-nums w-9 text-right shrink-0">
          {total > 0 ? `${Math.round(parte)}%` : '—'}
        </span>
      </div>
      <div className="mt-2 h-1 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(parte, 1)}%` }} />
      </div>
    </>
  );

  return (
    <section className="rounded-2xl border bg-card overflow-hidden animate-fade-in">
      <h2 className="text-[15px] font-semibold px-4 pt-4">Este mês, por {por}</h2>
      <ul className="mt-3 divide-y">
        {itens.map((i) => {
          const parte = total > 0 ? (i.valor / total) * 100 : 0;
          // "Sem loja atribuída" não tem id e não é um âmbito: fica visível e
          // plana. É a prova de que a soma por loja bate certo com o total.
          const tocavel = !!i.id && podeEscolher(i.id);
          return (
            <li key={i.id || 'sem'}>
              {tocavel ? (
                <button
                  type="button"
                  onClick={() => onEscolher(i.id)}
                  className="w-full px-4 py-3 text-left active:bg-accent/60
                             focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                >
                  <div className="flex items-center gap-2">
                    <div className="min-w-0 flex-1"><Conteudo i={i} parte={parte} /></div>
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  </div>
                </button>
              ) : (
                <div className="px-4 py-3"><Conteudo i={i} parte={parte} /></div>
              )}
            </li>
          );
        })}
      </ul>
      {!comIva && (
        <p className="px-4 pb-3 pt-1 text-[11px] text-muted-foreground">
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
      <section className="rounded-2xl border bg-card px-4 py-4 space-y-3">
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
    <section className="rounded-2xl border bg-card p-4 animate-fade-in">
      <h2 className="text-[15px] font-semibold">Últimos 30 dias</h2>
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

// A barra de baixo — o âmbito ao alcance do polegar.
//
// **Duas formas diferentes para dois níveis, e não a mesma fila duas vezes.**
// Antes eram duas filas do mesmo objecto empilhadas, e não se percebia qual
// era qual. Agora: segmentos numa calha para as empresas (o controlo que
// existe SEMPRE, sempre com o mesmo número de segmentos, sempre no mesmo
// sítio), e pastilhas soltas por cima para as lojas, que aparecem só quando a
// empresa tem lojas — e aparecem POR CIMA, para não deslocarem o controlo que
// se usa a toda a hora.
//
// Uma só língua de selecção nos dois níveis: `bg-primary` com o texto do
// portal — **excepto no tema escuro**, onde o `--primary` é um azul claro
// (217 92% 62%) e branco por cima dá 3,4:1, abaixo do mínimo. Aí o texto
// passa a ser o fundo da página: 5,6:1, medido. (O par `primary` +
// `primary-foreground` do portal tem este problema em TODOS os botões
// primários no escuro — aqui resolve-se só o que está neste ecrã.) O que NÃO está escolhido fica em
// `text-foreground` e não em `text-muted-foreground`: sobre `bg-muted` no tema
// escuro isso dava 3,4:1, e uma empresa por escolher não é texto secundário —
// é a próxima coisa em que se vai tocar.
function BarraDeAmbito({ empresas, empresaActiva, onEmpresa, lojas, lojaActiva, onLoja }) {
  const Segmento = ({ activo, onClick, children }) => (
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

  // Caixa normal e `whitespace-nowrap`, sem truncate: acabam os "PURPLE HO…".
  // A fila desliza, e uma pastilha meia-cortada na margem diz "há mais" melhor
  // do que reticências.
  const Pastilha = ({ activa, onClick, children }) => (
    <button
      type="button" onClick={onClick} aria-pressed={activa}
      className={`shrink-0 h-11 px-4 rounded-full text-sm font-semibold whitespace-nowrap
                  transition-colors duration-150
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
        activa ? 'bg-primary text-primary-foreground dark:text-background' : 'bg-muted text-foreground'
      }`}
    >
      {children}
    </button>
  );

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-30 bg-card border-t safe-area-inset-bottom">
      {lojas.length > 0 && (
        <div className="flex gap-2 overflow-x-auto px-3 py-1 border-b">
          <Pastilha activa={!lojaActiva} onClick={() => onLoja(null)}>Todas as lojas</Pastilha>
          {lojas.map((u) => (
            <Pastilha key={u.id} activa={lojaActiva === u.id} onClick={() => onLoja(u.id)}>
              {u.nome}
            </Pastilha>
          ))}
        </div>
      )}
      <div className="px-3 py-1.5">
        {/* `h-12` com `p-0.5`: a calha tem 48px e o enchimento come 4, o que
            deixa cada segmento com 44 — o mínimo do iOS, medido no ecrã. Com
            `h-11 p-[3px]` ficavam em 38 e nenhum teste apanhava isso. */}
        <div className="flex bg-muted rounded-xl p-0.5 h-12">
          <Segmento activo={empresaActiva === 'all'} onClick={() => onEmpresa('all')}>Grupo</Segmento>
          {empresas.map((c) => (
            <Segmento key={c.id} activo={empresaActiva === c.id} onClick={() => onEmpresa(c.id)}>
              {primeiraPalavra(c.nome)}
            </Segmento>
          ))}
        </div>
      </div>
    </nav>
  );
}

// --- O ecrã ------------------------------------------------------------------

export default function BolsoApp() {
  useManifestoDoBolso();
  const navigate = useNavigate();
  const { logout, user } = useAuth();

  const [empresa, setEmpresa] = useState(() => ler(CHAVE_EMPRESA, 'all'));
  const [unidade, setUnidade] = useState(() => ler(CHAVE_UNIDADE, null) || null);
  const [comIva, setComIva] = useState(() => ler(CHAVE_IVA, '1') !== '0');
  const [empresasConhecidas, setEmpresasConhecidas] = useState(lerEmpresas);
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [lidoAs, setLidoAs] = useState(null);

  // As lojas de cada empresa, guardadas à medida que se visitam. Sem isto, a
  // fila de lojas mostrava as da empresa ANTERIOR enquanto o pedido corria —
  // o mesmo defeito dos números, na navegação.
  const lojasPorEmpresa = useRef({});

  const carregar = useCallback(async (alvoEmpresa, alvoUnidade) => {
    setCarregando(true);
    setErro(null);
    try {
      const { data } = await getPainel(alvoEmpresa, alvoUnidade);
      setDados(data);
      setLidoAs(new Date().toISOString());
      if (alvoEmpresa === 'all' && (data?.ambito?.somadas || []).length) {
        setEmpresasConhecidas(data.ambito.somadas);
        guardar(CHAVE_EMPRESAS, JSON.stringify(data.ambito.somadas));
      }
      if (alvoEmpresa !== 'all') {
        lojasPorEmpresa.current[alvoEmpresa] = data?.ambito?.unidades || [];
      }
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

  // **Os números que estão no ecrã são DESTE âmbito?** O servidor devolve o
  // âmbito que somou, e é com ele que se compara — não com o que se pediu.
  // Enquanto não baterem, mostram-se esqueletos: sem isto, tocar em "Purple
  // House" deixava os números da Fordaimon à vista, por baixo do rótulo novo,
  // durante o tempo do pedido. O ecrã afirmava uma coisa falsa.
  const desteAmbito = !!dados
    && ambito?.pedido === empresa
    && (ambito?.unidade || null) === (unidade || null);
  const aCarregarNumeros = !desteAmbito;

  const lojas = desteAmbito
    ? (ambito?.unidades || [])
    : (lojasPorEmpresa.current[empresa] || []);

  const nomeDoAmbito = unidade
    ? (lojas.find((u) => u.id === unidade)?.nome || 'Loja')
    : (empresa === 'all'
        ? 'Todas as empresas'
        : empresasConhecidas.find((c) => c.id === empresa)?.nome || '');

  // A repartição reparte por empresa no grupo e por loja dentro de uma empresa
  // — e é o servidor que diz qual (`reparticao_por`). Cada linha só é uma porta
  // se o id for mesmo um âmbito que se possa escolher.
  const por = dados?.reparticao_por;
  const podeEscolher = (id) => (
    por === 'empresa'
      ? empresasConhecidas.some((c) => c.id === id)
      : lojas.some((u) => u.id === id)
  );
  const escolherDaReparticao = (id) => (por === 'empresa' ? escolherEmpresa(id) : escolherUnidade(id));

  const hoje = cartoes.hoje;

  return (
    <div className={`min-h-[100dvh] bg-muted/30 ${lojas.length ? 'pb-44' : 'pb-32'}`}>
      {/* Cabeçalho fixo. Sem `backdrop-filter` e sem transição: o nome do
          âmbito e a hora da leitura estão lá desde o primeiro pixel. Saber o
          que se está a ver não pode depender de se ter rolado. */}
      <header className="sticky top-0 z-20 bg-card border-b safe-area-inset-top">
        <div className="flex items-center gap-1 px-3 h-14">
          <div className="min-w-0 flex-1">
            <h1 className="font-heading font-bold text-base leading-tight truncate">{nomeDoAmbito}</h1>
            <p className="text-[11px] text-muted-foreground leading-tight truncate">
              {carregando ? 'A ler…' : (lidoAs ? `Lido ${quandoFoi(lidoAs)}` : '—')}
              {erro && <span className="text-destructive"> · falhou</span>}
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
        </div>
      </header>

      <main className="px-3 pt-3 pb-6 max-w-2xl mx-auto">
        {erro && (
          <section className="rounded-2xl border border-destructive/40 bg-destructive/10 p-3 flex items-start gap-2.5 mb-3">
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

        {/* A guarda do `empresa === 'all'` não é cosmética: sem ela, dentro da
            Fordaimon o ecrã gritava "Sem acesso a: Purple House, Lenha e
            Brasa" — que é verdade e é irrelevante, porque ninguém pediu que
            elas fossem somadas. */}
        {(ambito?.sem_acesso || []).length > 0 && empresa === 'all' && (
          <section className="rounded-2xl border border-warning/40 bg-warning/10 p-3 flex items-start gap-2.5 mb-3">
            <AlertTriangle className="h-4 w-4 text-warning-strong shrink-0 mt-0.5" />
            <p className="text-sm min-w-0">
              Sem acesso a: <strong>{ambito.sem_acesso.join(', ')}</strong>. Estes números não
              incluem essa faturação.
            </p>
          </section>
        )}

        {/* HOJE — o número que ele vem ver. Sem cartão à volta: o que não tem
            moldura não precisa de competir com as molduras de baixo. */}
        <section className="px-2">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[13px] font-semibold text-muted-foreground">Hoje</span>
            {hoje?.nota && <span className="text-[12px] text-muted-foreground">{hoje.nota}</span>}
          </div>

          {aCarregarNumeros ? (
            <Esqueleto className="h-11 w-56 mt-1 align-bottom" />
          ) : (
            <p className="mt-1 font-heading font-bold tabular-nums leading-none text-[2.75rem] tracking-[-0.03em]">
              <ValorGrande valor={comIva ? hoje?.valor : hoje?.valor_sem_iva} />
            </p>
          )}

          {!aCarregarNumeros && <Regua progresso={hoje?.progresso} />}

          {!aCarregarNumeros && (
            <p className="mt-2 text-[13px] text-muted-foreground tabular-nums">
              {/* **"do que ontem fez", nunca "a esta hora".** O `fin_sales`
                  guarda dias, não horas: o progresso é hoje contra o dia
                  INTEIRO de ontem. Prometer uma comparação horária seria a
                  mentira que este módulo existe para não dizer. */}
              {hoje?.progresso !== null && hoje?.progresso !== undefined ? (
                <>
                  <span className="font-semibold text-foreground">{Math.round(hoje.progresso)}%</span>
                  {' do que ontem fez · ontem '}{euros(hoje.anterior)}
                </>
              ) : 'Ontem não houve vendas — não há com que comparar.'}
            </p>
          )}

          {!aCarregarNumeros && !comIva && hoje?.valor_sem_iva === null && (
            <p className="mt-2 text-[12px] text-warning-strong">
              Esta origem não diz o valor sem IVA hoje.
            </p>
          )}
        </section>

        {/* MÊS e ANO — duas linhas, um cartão. Eram dois cartões iguais ao de
            cima e custavam duas rolagens. */}
        <section className="mt-4 rounded-2xl border bg-card overflow-hidden animate-fade-in">
          <div className="divide-y">
            <LinhaPeriodo rotulo="Este mês" dados={cartoes.mes} comIva={comIva} aCarregar={aCarregarNumeros} />
            <LinhaPeriodo rotulo="Este ano" dados={cartoes.ano} comIva={comIva} aCarregar={aCarregarNumeros} />
          </div>
          {/* **A linha que separa este painel do do Vendus.** O dele escreve
              "Mês Anterior: 44.421,91 €" sem dizer que esse valor é o mês
              INTEIRO enquanto o de cima são seis dias. Aqui diz-se — uma vez,
              e só quando há mesmo uma comparação para explicar. */}
          {!aCarregarNumeros && (cartoes.mes?.actual_rotulo || cartoes.ano?.actual_rotulo) && (
            <p className="px-4 py-2 bg-muted/40 text-[11px] text-muted-foreground border-t">
              As comparações usam só os dias já fechados de cada lado.
            </p>
          )}
        </section>

        <div className="mt-3">
          <Linha30Dias pontos={dados?.serie_dias} aCarregar={aCarregarNumeros} />
        </div>

        <div className="mt-3">
          <PorLoja itens={dados?.reparticao} por={por} comIva={comIva}
                   aCarregar={aCarregarNumeros}
                   podeEscolher={podeEscolher} onEscolher={escolherDaReparticao} />
        </div>

        {desteAmbito && (dados.dias_sem_vendas || []).length > 0 && (
          <section className="mt-3 rounded-2xl border bg-card p-4">
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
          <section className="mt-3 rounded-2xl border bg-card p-4 space-y-1">
            <h2 className="text-[15px] font-semibold text-muted-foreground">Origem dos números</h2>
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

        {/* Sair é raro e é irreversível. Rolar até ao fim é a barreira certa —
            e liberta no cabeçalho os 44px de que o nome do âmbito precisava. */}
        <button
          type="button"
          onClick={() => { logout(); navigate('/login'); }}
          className="mt-4 w-full h-12 rounded-2xl border bg-card px-4 flex items-center justify-between
                     active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="text-[13px] text-muted-foreground truncate">{user?.name || ''}</span>
          {/* **Sem vermelho.** Dava 4,03:1 no claro e 4,41:1 no escuro — abaixo
              do mínimo nos dois — e, pior, neste ecrã o vermelho já significa
              uma coisa: faturação a descer. Gastá-lo num botão de sair era
              tirar-lhe o significado que interessa. */}
          <span className="text-[15px] font-semibold shrink-0">Terminar sessão</span>
        </button>
      </main>

      <BarraDeAmbito
        empresas={empresasConhecidas}
        empresaActiva={empresa}
        onEmpresa={escolherEmpresa}
        lojas={lojas}
        lojaActiva={unidade}
        onLoja={escolherUnidade}
      />
    </div>
  );
}
