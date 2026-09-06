import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowDownRight, ArrowUpRight, Loader2, LogOut, RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { euros, getPainel, percentagem, quandoFoi, TIMEOUT_MS } from '@/lib/bolso';

// **Gestão de Bolso** — a faturação do grupo no telemóvel do gestor.
//
// Três decisões mandam neste ficheiro:
//
// 1. **O âmbito está a UM TOQUE, sempre à vista.** Contei os toques no portal
//    para chegar a "quanto fez Oeiras ontem": nove, e a escolha da empresa
//    perde-se ao mudar de secção. Aqui é uma fila de pastilhas fixa no topo, e
//    o que se escolheu sobrevive a fechar a app (`localStorage`) — um
//    telemóvel deita a página fora quando vai para o bolso.
// 2. **Um número que não se sabe escreve-se "—".** Nunca zero, nunca uma
//    percentagem inventada. Zero é uma afirmação sobre o negócio.
// 3. **A app diz sempre de quando são os números e o que somou.** Um painel
//    sem carimbo faz o gestor olhar às 13h para os números da manhã e decidir
//    com eles.
//
// O ecrã pede UM só pedido ao servidor (`GET /api/bolso/painel`) — com 4G de
// café, seis pedidos eram seis maneiras de meio painel ficar por preencher.

// As origens são chaves internas (`faturacao`, `vendus`, `moloni`) e não texto
// para ler. Um `capitalize` sobre elas escrevia "Faturacao", sem cedilha, no
// ecrã do dono.
const NOME_DA_ORIGEM = {
  faturacao: 'O nosso POS',
  vendus: 'Vendus',
  moloni: 'Moloni',
};

const CHAVE_AMBITO = 'bolso_empresa';
const CHAVE_IVA = 'bolso_com_iva';

const ler = (chave, omissao) => {
  try { return localStorage.getItem(chave) ?? omissao; } catch (e) { return omissao; }
};
const guardar = (chave, valor) => {
  try { localStorage.setItem(chave, valor); } catch (e) { /* modo privado */ }
};

// O manifesto do portal aponta para o POS (`start_url: /faturacao/pos`). Sem
// esta troca, "Adicionar ao ecrã principal" a partir do Bolso instalava um
// ícone que **abre o balcão da loja** — o manifesto é que manda, não o
// endereço que está à frente. Troca-se enquanto este ecrã está montado e
// repõe-se à saída, para não estragar a instalação do POS.
function useManifestoDoBolso() {
  useEffect(() => {
    const link = document.querySelector('link[rel="manifest"]');
    const anterior = link ? link.getAttribute('href') : null;
    if (link) link.setAttribute('href', '/bolso-manifest.json');

    // O iPhone ignora o `icons` do manifesto para o ícone do ecrã principal e
    // usa o `apple-touch-icon`. Sem ele, o atalho fica com uma miniatura da
    // página — ilegível ao lado dos outros ícones.
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

// --- Peças ------------------------------------------------------------------

function Pastilha({ activa, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={activa}
      className={`shrink-0 h-11 px-4 rounded-full border text-sm font-medium whitespace-nowrap transition-colors ${
        activa ? 'bg-primary text-primary-foreground border-primary' : 'bg-card hover:bg-accent'
      }`}
    >
      {children}
    </button>
  );
}

function Variacao({ valor }) {
  const texto = percentagem(valor);
  // Sem período anterior não há percentagem — e não se desenha nada. Um "0%"
  // aqui seria uma afirmação de estabilidade que ninguém mediu.
  if (texto === null) return null;
  const subiu = Number(valor) >= 0;
  const Icone = subiu ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`inline-flex items-center gap-0.5 text-sm font-semibold tabular-nums ${
      subiu ? 'text-success' : 'text-destructive'
    }`}>
      <Icone className="h-4 w-4 shrink-0" />
      {texto}
    </span>
  );
}

function Cartao({ titulo, dados, comIva, destaque, compacto }) {
  if (!dados) return null;
  const valor = comIva ? dados.valor : dados.valor_sem_iva;
  // **`compacto` existe por causa de uma quebra de linha vista no telemóvel**,
  // não por gosto: `€ 384 210,55` em `text-3xl` dentro de meia largura de um
  // ecrã de 375px partia o símbolo para uma linha e o número para outra. Um
  // valor em dinheiro partido ao meio lê-se mal e mede-se pior.
  return (
    <section className={`rounded-2xl border bg-card p-4 ${destaque ? 'border-primary/40' : ''}`}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{titulo}</p>
        <Variacao valor={dados.variacao} />
      </div>
      <p className={`font-heading font-bold tabular-nums leading-tight mt-1 whitespace-nowrap ${
        destaque ? 'text-4xl' : (compacto ? 'text-2xl' : 'text-3xl')
      }`}>
        {euros(valor)}
      </p>
      {/* A frase que diz o que foi comparado com o quê. Uma percentagem sem
          isto é uma afirmação sem contexto — e foi exactamente assim que o
          painel do Vendus anunciou −64% num mês que estava a subir. */}
      {(dados.comparacao || dados.nota) && (
        <p className="text-xs text-muted-foreground mt-1 leading-snug">
          {dados.nota || dados.comparacao}
        </p>
      )}
      {!comIva && dados.valor_sem_iva === null && (
        <p className="text-xs text-warning mt-1 leading-snug">
          Uma das origens não diz o valor sem IVA neste período.
        </p>
      )}
    </section>
  );
}

// Gráfico de linha em SVG puro. Sem biblioteca: são trinta pontos e uma
// polilinha, e uma dependência nova para isto seria mais código a carregar no
// telemóvel do que o desenho inteiro.
function Linha30Dias({ pontos }) {
  if (!pontos || pontos.length === 0) return null;
  const valores = pontos.map((p) => p.valor);
  const maximo = Math.max(...valores, 1);
  const L = 300;
  const A = 64;
  const passo = pontos.length > 1 ? L / (pontos.length - 1) : L;
  const caminho = pontos
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${(i * passo).toFixed(1)} ${(A - (p.valor / maximo) * A).toFixed(1)}`)
    .join(' ');
  return (
    <section className="rounded-2xl border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">Últimos 30 dias</p>
      <svg viewBox={`0 0 ${L} ${A}`} className="w-full h-20 mt-2" preserveAspectRatio="none" role="img"
           aria-label={`Faturação dos últimos ${pontos.length} dias`}>
        <path d={caminho} fill="none" stroke="currentColor" strokeWidth="2"
              className="text-primary" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between text-[11px] text-muted-foreground tabular-nums">
        <span>{pontos[0].dia.slice(8)}/{pontos[0].dia.slice(5, 7)}</span>
        <span>máx. {euros(maximo)}</span>
        <span>{pontos[pontos.length - 1].dia.slice(8)}/{pontos[pontos.length - 1].dia.slice(5, 7)}</span>
      </div>
    </section>
  );
}

function Barras6Meses({ meses }) {
  if (!meses || meses.length === 0) return null;
  const maximo = Math.max(...meses.map((m) => m.valor), 1);
  return (
    <section className="rounded-2xl border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">Últimos 6 meses</p>
      <div className="flex items-end gap-2 h-28 mt-3">
        {meses.map((m) => (
          <div key={m.mes} className="flex-1 flex flex-col items-center gap-1 min-w-0">
            <span className="text-[10px] text-muted-foreground tabular-nums truncate w-full text-center">
              {m.valor >= 1000 ? `${Math.round(m.valor / 1000)}k` : Math.round(m.valor)}
            </span>
            <div
              className={`w-full rounded-t ${m.em_curso ? 'bg-primary/40' : 'bg-primary'}`}
              style={{ height: `${Math.max(2, (m.valor / maximo) * 100)}%` }}
            />
            <span className="text-[11px] text-muted-foreground">{m.rotulo}</span>
          </div>
        ))}
      </div>
      {/* O mês corrente está a meio e por isso desenha-se mais claro. Sem esta
          nota, a última barra lê-se como uma queda. */}
      <p className="text-[11px] text-muted-foreground mt-1">
        O mês mais à direita está a decorrer.
      </p>
    </section>
  );
}

function Reparticao({ itens, por, comIva }) {
  if (!itens || itens.length === 0) return null;
  const total = itens.reduce((s, i) => s + (i.valor || 0), 0);
  return (
    <section className="rounded-2xl border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        Este mês, por {por}
      </p>
      <ul className="mt-2 divide-y">
        {itens.map((i) => (
          <li key={i.id || 'sem'} className="py-2.5 flex items-center gap-3">
            <span className="min-w-0 flex-1 truncate">{i.nome}</span>
            <span className="font-heading font-bold tabular-nums shrink-0">{euros(i.valor)}</span>
            <span className="text-xs text-muted-foreground tabular-nums w-10 text-right shrink-0">
              {total > 0 ? `${Math.round((i.valor / total) * 100)}%` : '—'}
            </span>
          </li>
        ))}
      </ul>
      {!comIva && (
        <p className="text-[11px] text-muted-foreground mt-2">
          A repartição mostra-se sempre com IVA.
        </p>
      )}
    </section>
  );
}

// --- O ecrã -----------------------------------------------------------------

export default function BolsoApp() {
  useManifestoDoBolso();
  const navigate = useNavigate();
  const { logout, user } = useAuth();

  const [empresa, setEmpresa] = useState(() => ler(CHAVE_AMBITO, 'all'));
  const [comIva, setComIva] = useState(() => ler(CHAVE_IVA, '1') !== '0');
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [lidoAs, setLidoAs] = useState(null);

  const carregar = useCallback(async (alvo) => {
    setCarregando(true);
    setErro(null);
    try {
      const { data } = await getPainel(alvo);
      setDados(data);
      setLidoAs(new Date().toISOString());
    } catch (e) {
      const status = e?.response?.status;
      if (status === 401) { logout(); navigate('/login'); return; }
      // Sem resposta não se aprendeu nada — e o que está no ecrã (se houver)
      // continua a valer, com o carimbo antigo à vista. Apagá-lo seria trocar
      // informação velha, mas datada, por nenhuma.
      setErro(
        e?.response
          ? (e.response.data?.detail || 'O servidor recusou este pedido.')
          : `Sem resposta do servidor em ${Math.round(TIMEOUT_MS / 1000)} segundos.`
      );
    } finally {
      setCarregando(false);
    }
  }, [logout, navigate]);

  useEffect(() => { carregar(empresa); }, [empresa, carregar]);

  // Numa app instalada, voltar ao ecrã não remonta a página: sem isto, o dono
  // abria o ícone às 13h e via os números da manhã com um carimbo credível.
  useEffect(() => {
    const aoVoltar = () => { if (!document.hidden) carregar(empresa); };
    document.addEventListener('visibilitychange', aoVoltar);
    return () => document.removeEventListener('visibilitychange', aoVoltar);
  }, [empresa, carregar]);

  const escolher = (id) => { setEmpresa(id); guardar(CHAVE_AMBITO, id); };
  const alternarIva = () => {
    setComIva((v) => { guardar(CHAVE_IVA, v ? '0' : '1'); return !v; });
  };

  const ambito = dados?.ambito;
  const cartoes = dados?.cartoes || {};

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b">
        <div className="flex items-center gap-2 px-3 h-14">
          <div className="min-w-0 flex-1">
            <p className="font-heading font-bold text-lg leading-none">Gestão de Bolso</p>
            <p className="text-[11px] text-muted-foreground truncate">
              {user?.name || user?.email}
            </p>
          </div>
          <Button variant="ghost" size="icon" className="h-10 w-10" onClick={alternarIva}
                  aria-label={comIva ? 'Mostrar sem IVA' : 'Mostrar com IVA'}>
            <span className="text-xs font-semibold">{comIva ? 'c/IVA' : 's/IVA'}</span>
          </Button>
          <Button variant="ghost" size="icon" className="h-10 w-10"
                  onClick={() => carregar(empresa)} disabled={carregando}
                  aria-label="Voltar a ler">
            {carregando ? <Loader2 className="h-5 w-5 animate-spin" /> : <RefreshCw className="h-5 w-5" />}
          </Button>
          <Button variant="ghost" size="icon" className="h-10 w-10"
                  onClick={() => { logout(); navigate('/login'); }} aria-label="Terminar sessão">
            <LogOut className="h-5 w-5" />
          </Button>
        </div>

        {/* O âmbito a UM toque, e sempre à vista. */}
        <div className="flex gap-2 overflow-x-auto px-3 pb-2.5">
          <Pastilha activa={empresa === 'all'} onClick={() => escolher('all')}>Grupo</Pastilha>
          {(ambito?.somadas || []).map((c) => (
            <Pastilha key={c.id} activa={empresa === c.id} onClick={() => escolher(c.id)}>
              {c.nome}
            </Pastilha>
          ))}
        </div>
      </header>

      <main className="p-3 space-y-3 max-w-2xl mx-auto pb-10">
        {erro && (
          <section className="rounded-2xl border border-destructive/40 bg-destructive/10 p-4 flex items-start gap-2.5">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="font-medium">Não foi possível ler agora.</p>
              <p className="text-sm text-muted-foreground mt-0.5 break-words">{erro}</p>
              {dados && (
                <p className="text-sm text-muted-foreground mt-1">
                  O que está em baixo é a leitura anterior {quandoFoi(lidoAs) || ''}.
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
            {/* O aviso de âmbito. Sem uma linha em `fin_company_members`, o
                "grupo" devolve zero sem um único erro — e um total incompleto
                lê-se como um mau mês, não como um problema de configuração. */}
            {(ambito?.sem_acesso || []).length > 0 && (
              <section className="rounded-2xl border border-warning/40 bg-warning/10 p-3 flex items-start gap-2.5">
                <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
                <p className="text-sm min-w-0">
                  Sem acesso a: <strong>{ambito.sem_acesso.join(', ')}</strong>. Estes números
                  não incluem essa faturação.
                </p>
              </section>
            )}

            <Cartao titulo="Ontem" dados={cartoes.ontem} comIva={comIva} destaque />
            <Cartao titulo="Hoje" dados={cartoes.hoje} comIva={comIva} />
            <Cartao titulo="Mês" dados={cartoes.mes} comIva={comIva} compacto />
            <Cartao titulo="Ano" dados={cartoes.ano} comIva={comIva} compacto />

            <Linha30Dias pontos={dados.serie_dias} />
            <Barras6Meses meses={dados.serie_meses} />
            <Reparticao itens={dados.reparticao} por={dados.reparticao_por} comIva={comIva} />

            {(dados.dias_sem_vendas || []).length > 0 && (
              <section className="rounded-2xl border bg-muted/50 p-3">
                <p className="text-sm">
                  <strong>Sem vendas registadas</strong> em{' '}
                  {dados.dias_sem_vendas.map((d) => d.slice(8) + '/' + d.slice(5, 7)).join(', ')}.
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Pode ser um dia fechado — ou uma leitura que não correu. Veja as leituras em baixo.
                </p>
              </section>
            )}

            {/* A proveniência, sempre à vista e nunca escondida num ícone. */}
            <section className="rounded-2xl border bg-card p-3 space-y-1">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Origem dos números</p>
              {(dados.leituras || []).map((l) => (
                <p key={l.origem} className="text-xs text-muted-foreground">
                  <span className="text-foreground">{NOME_DA_ORIGEM[l.origem] || l.origem}</span>
                  {' · '}lido {quandoFoi(l.terminou_em) || 'em data desconhecida'}
                  {l.completa === false && (
                    <span className="text-warning"> · com queixas</span>
                  )}
                </p>
              ))}
              <p className="text-xs text-muted-foreground pt-1">
                A somar: {(ambito?.somadas || []).map((c) => c.nome).join(' · ') || '—'}
              </p>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
