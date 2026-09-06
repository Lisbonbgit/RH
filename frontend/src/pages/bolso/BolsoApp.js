import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Loader2, LogOut, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { euros, getPainel, percentagem, quandoFoi, TIMEOUT_MS } from '@/lib/bolso';

// **Gestão de Bolso** — a faturação do grupo no telemóvel do gestor.
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
// Aqui a comparação é sempre com o **período equivalente** (os mesmos dias do
// mês anterior, os mesmos dias do ano anterior) e o rótulo diz exactamente o
// que foi comparado com o quê. É por isso que os números deste ecrã **não vão
// bater** com os do painel do Vendus — e é de propósito.
//
// O cartão de HOJE tem tratamento próprio: em vez de uma percentagem contra
// ontem inteiro (que às nove da manhã dá −85%, todos os dias), mostra quanto
// já vai **do que ontem fez**. Ver `bolso.cartao_de_hoje` no servidor.
//
// ## O âmbito, a três níveis
//
// Grupo → Empresa → Loja, na barra de baixo, com o polegar. A escolha
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
    document.title = 'Gestão de Bolso';
    return () => {
      if (link && anterior) link.setAttribute('href', anterior);
      apple.remove();
      document.title = titulo;
    };
  }, []);
}

// --- Peças -------------------------------------------------------------------

// A medalha do painel do Vendus: verde a subir, vermelha a descer. Só aparece
// quando há mesmo uma percentagem — sem período anterior não se pinta nada,
// porque uma medalha cinzenta a dizer "0%" seria uma afirmação que ninguém
// mediu.
function Medalha({ variacao }) {
  const texto = percentagem(variacao);
  if (texto === null) return null;
  const subiu = Number(variacao) >= 0;
  return (
    <span className={`shrink-0 rounded-md px-2 py-1 text-sm font-bold tabular-nums ${
      subiu ? 'bg-success text-success-foreground' : 'bg-destructive text-destructive-foreground'
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
    <span className="shrink-0 rounded-md bg-primary/10 text-primary px-2 py-1 text-sm font-bold tabular-nums">
      {Math.round(progresso)}% de ontem
    </span>
  );
}

function CartaoGrande({ titulo, dados, comIva }) {
  if (!dados) return null;
  const valor = comIva ? dados.valor : dados.valor_sem_iva;
  const rotulo = dados.anterior_rotulo || dados.comparacao;
  return (
    <section className="rounded-2xl border bg-card overflow-hidden">
      <div className="px-5 pt-4 pb-5">
        <p className="font-heading font-bold text-lg">{titulo}</p>
        {/* `whitespace-nowrap` não é decoração: `€ 384 210,55` a este tamanho
            parte o símbolo para uma linha e o número para outra, e um valor em
            dinheiro partido ao meio lê-se mal e mede-se pior. */}
        <p className="font-heading font-bold text-primary tabular-nums whitespace-nowrap text-[2.6rem] leading-none mt-3">
          {euros(valor)}
        </p>
        {!comIva && dados.valor_sem_iva === null && (
          <p className="text-xs text-warning mt-2">
            Uma das origens não diz o valor sem IVA neste período.
          </p>
        )}
      </div>
      <div className="border-t bg-muted/40 px-5 py-3 flex items-center gap-2.5 flex-wrap">
        <Medalha variacao={dados.variacao} />
        <MedalhaDeProgresso progresso={dados.progresso} />
        <span className="text-sm text-muted-foreground min-w-0">
          {dados.anterior !== null && dados.anterior !== undefined ? (
            <>
              <span className="font-medium text-foreground">{rotulo}:</span>{' '}
              <span className="tabular-nums">{euros(dados.anterior)}</span>
            </>
          ) : (
            dados.nota || 'sem período anterior para comparar'
          )}
        </span>
      </div>
      {/* **A linha que separa este painel do outro.** O do Vendus escreve "Mês
          Anterior: 44.421,91 €" — e não diz que esse valor é o mês INTEIRO
          enquanto o de cima são seis dias. Aqui diz-se o que foi medido de
          cada lado, e a percentagem deixa de poder enganar. */}
      {dados.actual_rotulo && (
        <p className="px-5 pb-3 text-xs text-muted-foreground">
          Compara {dados.actual_rotulo} — os dias já fechados.
        </p>
      )}
    </section>
  );
}

function PorLoja({ itens, por, comIva }) {
  if (!itens || itens.length === 0) return null;
  const total = itens.reduce((s, i) => s + (i.valor || 0), 0);
  return (
    <section className="rounded-2xl border bg-card overflow-hidden">
      <p className="font-heading font-bold text-lg px-5 pt-4">Este mês, por {por}</p>
      <ul className="mt-2 divide-y">
        {itens.map((i) => (
          <li key={i.id || 'sem'} className="px-5 py-3 flex items-center gap-3">
            <span className="min-w-0 flex-1 truncate">{i.nome}</span>
            <span className="font-heading font-bold tabular-nums shrink-0">{euros(i.valor)}</span>
            <span className="text-xs text-muted-foreground tabular-nums w-10 text-right shrink-0">
              {total > 0 ? `${Math.round((i.valor / total) * 100)}%` : '—'}
            </span>
          </li>
        ))}
      </ul>
      {!comIva && (
        <p className="px-5 pb-3 pt-1 text-[11px] text-muted-foreground">
          A repartição mostra-se sempre com IVA.
        </p>
      )}
    </section>
  );
}

function Linha30Dias({ pontos }) {
  if (!pontos || pontos.length === 0) return null;
  const maximo = Math.max(...pontos.map((p) => p.valor), 1);
  const L = 300;
  const A = 64;
  const passo = pontos.length > 1 ? L / (pontos.length - 1) : L;
  const caminho = pontos
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${(i * passo).toFixed(1)} ${(A - (p.valor / maximo) * A).toFixed(1)}`)
    .join(' ');
  return (
    <section className="rounded-2xl border bg-card p-5">
      <p className="font-heading font-bold text-lg">Últimos 30 dias</p>
      <svg viewBox={`0 0 ${L} ${A}`} className="w-full h-20 mt-3" preserveAspectRatio="none"
           role="img" aria-label="Faturação dos últimos 30 dias">
        <path d={caminho} fill="none" stroke="currentColor" strokeWidth="2"
              className="text-primary" vectorEffect="non-scaling-stroke" />
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
// painel que o dono já usa. Duas filas, e a segunda só existe quando a
// empresa escolhida tem lojas: uma fila vazia a ocupar espaço é pior do que
// não haver fila.
function BarraDeAmbito({ empresas, empresaActiva, onEmpresa, unidades, unidadeActiva, onUnidade }) {
  const Separador = ({ activo, onClick, children }) => (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={activo}
      className={`shrink-0 h-12 px-4 text-sm font-semibold uppercase tracking-wide whitespace-nowrap border-b-2 transition-colors ${
        activo ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'
      }`}
    >
      {children}
    </button>
  );

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-20 bg-card border-t"
         style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
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
  const nomeDoAmbito = unidade
    ? (unidades.find((u) => u.id === unidade)?.nome || 'Loja')
    : (empresa === 'all'
        ? 'Grupo Lisbonb'
        : (ambito?.somadas || []).find((c) => c.id === empresa)?.nome || '');

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="sticky top-0 z-10 bg-card/95 backdrop-blur border-b">
        <div className="flex items-center gap-2 px-4 h-14">
          <div className="min-w-0 flex-1">
            <p className="font-heading font-bold text-base leading-none">Gestão de Bolso</p>
            <p className="text-[11px] text-muted-foreground truncate mt-0.5">{nomeDoAmbito}</p>
          </div>
          <Button variant="ghost" size="icon" className="h-10 w-10" onClick={alternarIva}
                  aria-label={comIva ? 'Mostrar sem IVA' : 'Mostrar com IVA'}>
            <span className="text-xs font-semibold">{comIva ? 'c/IVA' : 's/IVA'}</span>
          </Button>
          <Button variant="ghost" size="icon" className="h-10 w-10"
                  onClick={() => carregar(empresa, unidade)} disabled={carregando}
                  aria-label="Voltar a ler">
            {carregando ? <Loader2 className="h-5 w-5 animate-spin" /> : <RefreshCw className="h-5 w-5" />}
          </Button>
          <Button variant="ghost" size="icon" className="h-10 w-10"
                  onClick={() => { logout(); navigate('/login'); }} aria-label="Terminar sessão">
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </header>

      {/* Espaço em baixo para a barra de âmbito não tapar o último cartão. */}
      <main className="px-3 py-3 space-y-3 max-w-2xl mx-auto pb-40">
        {/* O carimbo, no mesmo sítio onde ele o lê hoje. */}
        <p className="text-center">
          <span className="inline-block rounded-full bg-primary/10 text-primary text-sm px-4 py-1.5">
            Última atualização: {quandoFoi(lidoAs)?.replace('às ', '') || '—'}
          </span>
        </p>

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

        {carregando && !dados && (
          <div className="py-24 flex justify-center">
            <Loader2 className="h-7 w-7 animate-spin text-primary" />
          </div>
        )}

        {dados && (
          <>
            {(ambito?.sem_acesso || []).length > 0 && empresa === 'all' && (
              <section className="rounded-2xl border border-warning/40 bg-warning/10 p-3 flex items-start gap-2.5">
                <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
                <p className="text-sm min-w-0">
                  Sem acesso a: <strong>{ambito.sem_acesso.join(', ')}</strong>. Estes números não
                  incluem essa faturação.
                </p>
              </section>
            )}

            <CartaoGrande titulo="Faturação Hoje" dados={cartoes.hoje} comIva={comIva} />
            <CartaoGrande titulo="Faturação Mensal" dados={cartoes.mes} comIva={comIva} />
            <CartaoGrande titulo="Faturação Anual" dados={cartoes.ano} comIva={comIva} />

            <PorLoja itens={dados.reparticao} por={dados.reparticao_por} comIva={comIva} />
            <Linha30Dias pontos={dados.serie_dias} />

            {(dados.dias_sem_vendas || []).length > 0 && (
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

            <section className="rounded-2xl border bg-card p-4 space-y-1">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Origem dos números
              </p>
              {(dados.leituras || []).map((l) => (
                <p key={l.origem} className="text-xs text-muted-foreground">
                  <span className="text-foreground">{NOME_DA_ORIGEM[l.origem] || l.origem}</span>
                  {' · '}lido {quandoFoi(l.terminou_em) || 'em data desconhecida'}
                  {l.completa === false && <span className="text-warning"> · com queixas</span>}
                </p>
              ))}
            </section>
          </>
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
