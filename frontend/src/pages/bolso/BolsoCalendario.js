import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { getCalendario, getContagem } from '@/lib/bolso';
import {
  DIAS_DA_SEMANA, FILTROS, MESES, NOMES_DAS_AUSENCIAS, VISTAS, ausenciasDoDia, celulaDaSemana, dataCurta,
  diaAoLado, diasComPonto, feriadosDoMes, filtrarPorLoja, hojeIso, intervaloCurto, isoDe, juntarMeses,
  linhaDaContagem, lista, mensagemDeErro, mesAoLado, mesesDaSemana, minhasIdas, nomeCurtoDaLoja, quantosDias,
  semanaDe, tituloDaSemana, tituloDoDia, tituloDoMes,
} from '@/lib/calendario';
import {
  BotaoMenu, Calha, GrelhaDoMes, MenuLateral, Segmento, guardar, ler, useManifestoDoBolso,
} from './partilhado';
import PainelIda from './PainelIda';

// **Calendário das lojas** — onde falta gente, para a Carol e a Débora taparem.
//
// O servidor calcula os buracos a cada pedido (horário das lojas + escala de cada pessoa +
// ausências aprovadas + idas) e manda o mês inteiro num pedido; este ecrã só desenha. As
// contas do ecrã vivem em `lib/calendario.js` (puras, testadas em Node).
//
// Em cima: ☰, a semana (ou o mês), ‹ › e Semana | Mês | Lista | Contagem. Em baixo: Pessoal |
// Geral | Férias. Por baixo das vistas, o filtro de loja (Todas | Alfragide | …; a Contagem não
// o tem). Vista, filtro e loja lembram-se no `localStorage` (sem ele, abre em Semana/Geral/Todas).
// Há um só dia escolhido para todas as vistas, e o mês à vista é sempre o dele. «Tapar» e
// «Marcar ida» só existem para quem pode marcar (o servidor diz `pode_marcar`; o contabilista
// só lê).

const CHAVE_VISTA = 'bolso_cal_vista';
const CHAVE_FILTRO = 'bolso_cal_filtro';
const CHAVE_LOJA = 'bolso_cal_loja';
const COR_DO_PONTO = { geral: 'bg-destructive', pessoal: 'bg-primary', ferias: 'bg-warning' };
const lerOpcao = (chave, opcoes, omissao) => {
  const v = ler(chave, omissao);
  return opcoes.includes(v) ? v : omissao;
};
const etiqueta = (p) => (p.origem === 'escala' ? 'escala' : p.extra ? 'extra' : 'ida');
const chaveDoMes = (ano, mes) => isoDe(ano, mes, 1).slice(0, 7);

const Esqueleto = () => (
  <div aria-hidden="true" className="mt-3 h-40 rounded-2xl bg-muted-foreground/15 motion-safe:animate-pulse" />
);

function Cartao({ titulo, subtitulo, children }) {
  return (
    <section className="mt-3 rounded-2xl border bg-card overflow-hidden">
      <header className="px-4 pt-3 pb-2">
        <h2 className="text-[15px] font-semibold first-letter:uppercase">{titulo}</h2>
        {subtitulo && <p className="text-[12px] text-warning-strong">{subtitulo}</p>}
      </header>
      {children}
    </section>
  );
}

// Uma linha que é botão quando se pode tocar (abrir a ida) e texto quando não.
function Linha({ onClick, children }) {
  const forma = 'w-full min-h-11 flex items-center gap-2 text-left text-[14px]';
  return onClick ? (
    <button
      type="button" onClick={onClick}
      className={`${forma} rounded-lg active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
    >
      {children}
    </button>
  ) : <div className={forma}>{children}</div>;
}

function LojaDoDia({ loja, data, podeMarcar, onTapar, onIda, soBuracos = false }) {
  if (loja.estado === 'fechada') {
    return (
      <li className="px-4 py-3 flex items-baseline justify-between gap-2 text-muted-foreground">
        <span className="font-semibold">{loja.nome}</span>
        <span className="text-[13px]">fechada</span>
      </li>
    );
  }
  const ninguem = loja.pessoas.length === 0;
  return (
    <li className="px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">{loja.nome}</span>
        <span className="text-[12px] text-muted-foreground tabular-nums">{intervaloCurto(loja.abre, loja.fecha)}</span>
      </div>
      {loja.feriados.length > 0 && <p className="text-[12px] text-warning-strong">{loja.feriados.join(' · ')}</p>}
      {!soBuracos && loja.pessoas.map((p) => (
        <Linha key={`${p.origem}-${p.ida_id || p.user_id || p.nome}-${p.inicio}`} onClick={p.ida_id && podeMarcar ? () => onIda(p.ida_id) : null}>
          <span className="min-w-0 flex-1 truncate">{p.nome}</span>
          <span className="tabular-nums text-muted-foreground">{intervaloCurto(p.inicio, p.fim)}</span>
          <span className={`text-[12px] font-semibold ${p.origem === 'escala' ? 'text-muted-foreground' : 'text-primary'}`}>
            {etiqueta(p)}
          </span>
        </Linha>
      ))}
      {loja.buracos.map((b) => (
        <div
          key={b.inicio} data-buraco={ninguem ? 'ninguem' : 'falta'}
          className={`mt-2 flex items-center gap-2 rounded-xl py-1 pl-3 pr-1 ${
            ninguem ? 'bg-destructive-strong text-white' : 'bg-warning/15 text-warning-strong'}`}
        >
          {/* «ninguém» em pastilha cheia: branco sobre `destructive-strong` dá 6,5:1 (claro) e
              6,0:1 (escuro). O `text-destructive` sobre `bg-destructive/10` dava ≈3,5:1 e 4,0:1
              — e `text-destructive-strong` no escuro dá 3,0:1 (o token foi feito para fundo). */}
          <span className="flex-1 text-[14px] font-semibold">
            {ninguem ? 'ninguém' : `falta ${intervaloCurto(b.inicio, b.fim)}`}
          </span>
          {podeMarcar && (
            <button
              type="button"
              onClick={() => onTapar({ data, location_id: loja.location_id, nome: loja.nome, inicio: b.inicio, fim: b.fim })}
              className="h-11 px-4 rounded-lg border bg-card font-semibold text-foreground
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Tapar
            </button>
          )}
        </div>
      ))}
    </li>
  );
}

function IdaLinha({ ida, comNome, onIda }) {
  return (
    <Linha onClick={onIda ? () => onIda(ida.id) : null}>
      <span className="min-w-0 flex-1 truncate">{comNome ? `${ida.nome} · ${ida.loja}` : ida.loja}</span>
      <span className="tabular-nums text-muted-foreground">{intervaloCurto(ida.inicio, ida.fim)}</span>
    </Linha>
  );
}

function AusenciaLinha({ ausencia }) {
  return (
    <div className="py-2 text-[14px]">
      <p className="font-semibold">{ausencia.nome} · {NOMES_DAS_AUSENCIAS[ausencia.tipo] || ausencia.tipo}</p>
      <p className="text-[12px] text-muted-foreground">
        {dataCurta(ausencia.inicio)}–{dataCurta(ausencia.fim)}{ausencia.loja ? ` · ${ausencia.loja}` : ''}
      </p>
    </div>
  );
}

// O dia escolhido, por baixo da grelha, conforme o filtro.
function Dia({ dados, iso, filtro, onTapar, onIda }) {
  const dia = (dados.dias || []).find((d) => d.data === iso);
  if (!dia) return null;
  const feriados = dia.feriados.length ? dia.feriados.join(' · ') : null;
  const abrirIda = dados.pode_marcar ? onIda : null;
  if (filtro === 'pessoal') {
    const idas = minhasIdas(dados).filter((i) => i.data === iso);
    return (
      <Cartao titulo={tituloDoDia(iso)} subtitulo={feriados}>
        <div className="px-4 pb-3">
          {idas.length === 0 && <p className="py-2 text-[14px] text-muted-foreground">Sem idas tuas neste dia.</p>}
          {idas.map((i) => <IdaLinha key={i.id} ida={i} onIda={abrirIda} />)}
        </div>
      </Cartao>
    );
  }
  if (filtro === 'ferias') {
    const ausencias = ausenciasDoDia(dados, iso);
    return (
      <Cartao titulo={tituloDoDia(iso)} subtitulo={feriados}>
        <div className="px-4 pb-2 divide-y">
          {ausencias.length === 0 && <p className="py-2 text-[14px] text-muted-foreground">Ninguém ausente neste dia.</p>}
          {ausencias.map((a) => <AusenciaLinha key={`${a.nome}-${a.inicio}`} ausencia={a} />)}
        </div>
      </Cartao>
    );
  }
  if (!dados.lojas.length) {
    return (
      <Cartao titulo={tituloDoDia(iso)} subtitulo={feriados}>
        <p className="px-4 pb-3 text-[14px] text-muted-foreground">
          Ainda nenhuma loja tem horário. Defina-o em Locais, no portal.
        </p>
      </Cartao>
    );
  }
  return (
    <Cartao titulo={tituloDoDia(iso)} subtitulo={feriados}>
      <ul className="divide-y border-t">
        {dia.lojas.map((l) => (
          <LojaDoDia key={l.location_id} loja={l} data={iso} podeMarcar={dados.pode_marcar} onTapar={onTapar} onIda={onIda} />
        ))}
      </ul>
    </Cartao>
  );
}

function Lista({ dados, filtro, hoje, onTapar, onIda }) {
  const dias = lista(dados, filtro, hoje);
  if (!dias.length) {
    const nada = { geral: 'Sem buracos nem idas', pessoal: 'Sem idas tuas', ferias: 'Ninguém ausente' }[filtro];
    return <p className="mt-6 text-center text-[14px] text-muted-foreground">{nada} neste mês.</p>;
  }
  const abrirIda = dados.pode_marcar ? onIda : null;
  return dias.map((d) => (
    <Cartao key={d.data} titulo={tituloDoDia(d.data)}>
      {d.buracos.length > 0 && (
        <ul className="divide-y border-t">
          {d.buracos.map((l) => (
            <LojaDoDia key={l.location_id} loja={l} data={d.data} podeMarcar={dados.pode_marcar} onTapar={onTapar} onIda={onIda} soBuracos />
          ))}
        </ul>
      )}
      {d.idas.length > 0 && (
        <div className="px-4 pb-2 border-t">
          {d.idas.map((i) => <IdaLinha key={i.id} ida={i} comNome={filtro === 'geral'} onIda={abrirIda} />)}
        </div>
      )}
      {d.ausencias.length > 0 && (
        <div className="px-4 pb-2 divide-y border-t">
          {d.ausencias.map((a) => <AusenciaLinha key={`${a.nome}-${a.inicio}`} ausencia={a} />)}
        </div>
      )}
    </Cartao>
  ));
}

// As cores das células são as da agenda do dia (contrastes medidos lá): «—» a vermelho cheio,
// a falta a âmbar; «ok» e «fech.» discretos, para os buracos saltarem à vista.
const COR_DA_CELULA = {
  ninguem: 'bg-destructive-strong text-white font-semibold',
  falta: 'bg-warning/15 text-warning-strong font-semibold',
  minha: 'text-primary font-semibold',
  ok: 'text-muted-foreground',
  fechada: 'text-muted-foreground',
  vazia: '',
};
const GRELHA_DA_SEMANA = 'grid grid-cols-[4rem_repeat(7,minmax(0,1fr))] gap-0.5';

// A Semana: as lojas em linhas, os 7 dias (seg a dom) em colunas; tocar numa célula escolhe o
// dia. Cabe em 375px: 4rem para o nome e ~38px por dia; «10h–14h» parte a seguir ao traço.
function Semana({ dados, filtro, escolhido, onTocar }) {
  const dias = semanaDe(escolhido);
  const doDia = (iso, id) => (dados.dias || []).find((d) => d.data === iso)?.lojas.find((l) => l.location_id === id);
  return (
    <section className="rounded-2xl border bg-card p-1">
      <div data-cabecalho="" aria-hidden="true" className={`${GRELHA_DA_SEMANA} pb-1 text-center text-[11px] tabular-nums`}>
        <span />
        {dias.map((iso, i) => (
          <span key={iso} className={iso === escolhido ? 'font-bold text-foreground' : 'font-semibold text-muted-foreground'}>
            {DIAS_DA_SEMANA[i][0].toUpperCase()} {Number(iso.slice(8))}
          </span>
        ))}
      </div>
      {dados.lojas.map((loja) => (
        <div key={loja.id} data-loja={loja.id} className={`${GRELHA_DA_SEMANA} mt-0.5`}>
          <span className="self-center truncate pl-1 text-[12px] font-semibold">{nomeCurtoDaLoja(loja.nome)}</span>
          {dias.map((iso) => {
            const c = celulaDaSemana(doDia(iso, loja.id), filtro, dados.eu);
            const [antes, ...depois] = c.texto.split('–');
            return (
              <button
                key={iso} type="button" data-celula={iso} aria-pressed={iso === escolhido} onClick={() => onTocar(iso)}
                aria-label={`${loja.nome}, ${tituloDoDia(iso)}${c.texto ? `: ${c.estado === 'ninguem' ? 'ninguém' : c.texto}` : ''}`}
                className={`h-11 min-w-0 overflow-hidden break-words rounded-md px-0.5 text-[11px] leading-tight tabular-nums
                            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${COR_DA_CELULA[c.estado]} ${
                  iso === escolhido ? 'ring-2 ring-inset ring-primary' : ''}`}
              >
                {antes}{depois.length > 0 && <>–<wbr />{depois.join('–')}</>}
              </button>
            );
          })}
        </div>
      ))}
    </section>
  );
}

// Férias na Semana: as ausências que tocam a semana, sem grelha.
function FeriasDaSemana({ dados, escolhido }) {
  const dias = semanaDe(escolhido);
  const ausencias = (dados.ausencias || []).filter((a) => a.inicio <= dias[6] && a.fim >= dias[0]);
  return (
    <Cartao titulo="Ausências da semana">
      <div className="px-4 pb-2 divide-y">
        {ausencias.length === 0 && <p className="py-2 text-[14px] text-muted-foreground">Ninguém ausente nesta semana.</p>}
        {ausencias.map((a) => <AusenciaLinha key={`${a.nome}-${a.inicio}`} ausencia={a} />)}
      </div>
    </Cartao>
  );
}

// O filtro de loja: «Todas» + uma pastilha por loja, de 44px. Com muitas lojas a fila desliza
// para o lado sozinha (a página não). As cores são as das pessoas no painel da ida.
function FiltroDeLoja({ lojas, escolhida, onEscolher }) {
  const pastilha = (id, nome) => (
    <button
      key={id || 'todas'} type="button" aria-pressed={escolhida === id} onClick={() => onEscolher(id)}
      className={`h-11 shrink-0 px-4 rounded-full text-sm font-semibold focus-visible:outline-none
                  focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${escolhida === id
        ? 'bg-primary text-primary-foreground dark:text-background' : 'bg-muted text-foreground'}`}
    >
      {nome}
    </button>
  );
  return (
    <div role="group" aria-label="Filtro de loja" className="flex gap-2 overflow-x-auto px-3 pb-2">
      {pastilha('', 'Todas')}
      {lojas.map((l) => pastilha(l.id, nomeCurtoDaLoja(l.nome)))}
    </div>
  );
}

// «Débora · outubro 18 dias · 2026 60 dias»; tocar abre os meses um a um.
function Contagem({ linhas, ano, mes }) {
  const [aberta, setAberta] = useState(null);
  if (!linhas) return <Esqueleto />;
  if (!linhas.length) return <p className="mt-6 text-center text-[14px] text-muted-foreground">Ainda não há idas em {ano}.</p>;
  return (
    <section className="mt-3 rounded-2xl border bg-card overflow-hidden">
      <ul className="divide-y">
        {linhas.map((l) => (
          <li key={l.user_id}>
            <button
              type="button" aria-expanded={aberta === l.user_id}
              onClick={() => setAberta(aberta === l.user_id ? null : l.user_id)}
              className="w-full min-h-12 px-4 py-3 flex items-center gap-2 text-left text-[15px]
                         active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
            >
              <span className="min-w-0 flex-1">{linhaDaContagem(l, ano, mes)}</span>
              <ChevronRight className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${aberta === l.user_id ? 'rotate-90' : ''}`} />
            </button>
            {aberta === l.user_id && (
              <ol className="grid grid-cols-2 gap-x-4 px-4 pb-3 text-[13px] tabular-nums">
                {MESES.map((nome, i) => (
                  <li key={nome} className={`flex justify-between py-0.5 ${i + 1 === mes ? 'font-semibold' : 'text-muted-foreground'}`}>
                    <span>{nome}</span>
                    <span>{quantosDias(l.meses[i])}</span>
                  </li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function BolsoCalendario() {
  useManifestoDoBolso();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const hoje = hojeIso();
  const [vista, setVista] = useState(() => lerOpcao(CHAVE_VISTA, VISTAS, 'semana'));
  const [filtro, setFiltro] = useState(() => lerOpcao(CHAVE_FILTRO, FILTROS, 'geral'));
  const [lojaGuardada, setLojaGuardada] = useState(() => ler(CHAVE_LOJA, ''));
  // Um só dia escolhido para todas as vistas; o mês à vista é o dele.
  const [escolhido, setEscolhido] = useState(hoje);
  const ano = Number(escolhido.slice(0, 4));
  const mes = Number(escolhido.slice(5, 7));
  // As respostas do servidor, por mês ('AAAA-MM'): na Semana são duas quando ela atravessa o mês.
  const [respostas, setRespostas] = useState({});
  const [contagem, setContagem] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [erroDaContagem, setErroDaContagem] = useState(null);
  const [menu, setMenu] = useState(false);
  const [painel, setPainel] = useState(null);
  // Cada pedido leva um número; só o último escreve no ecrã. Sem isto, tocar ‹ › depressa
  // deixava a resposta de um mês antigo chegar por último e ficar.
  const pedido = useRef(0);
  const pedidoDaContagem = useRef(0);
  // Cada abertura do painel é uma montagem nova (a `key`), para o formulário começar sempre
  // no que se tocou e não no que ficou da vez anterior.
  const aberturas = useRef(0);

  const semSessao = useCallback(() => { logout(); navigate('/login'); }, [logout, navigate]);

  // Os meses que o ecrã precisa, numa chave estável: tocar noutro dia da mesma semana (ou do
  // mesmo mês) não volta a pedir nada.
  const meses = (vista === 'semana' ? mesesDaSemana(escolhido) : [{ ano, mes }])
    .map((m) => chaveDoMes(m.ano, m.mes)).join(' ');

  const carregar = useCallback(async () => {
    pedido.current += 1;
    const meu = pedido.current;
    setCarregando(true);
    setErro(null);
    try {
      const pedidos = meses.split(' ');
      const lidas = await Promise.all(pedidos.map((m) => getCalendario(Number(m.slice(0, 4)), Number(m.slice(5)))));
      if (meu === pedido.current) setRespostas(Object.fromEntries(pedidos.map((m, i) => [m, lidas[i].data])));
    } catch (e) {
      if (e?.response?.status === 401) { semSessao(); return; }
      if (meu === pedido.current) setErro(mensagemDeErro(e));
    } finally {
      if (meu === pedido.current) setCarregando(false);
    }
  }, [meses, semSessao]);

  // A mesma guarda do mês, com o erro à parte: pedir de novo limpa só o da contagem.
  const carregarContagem = useCallback(async () => {
    pedidoDaContagem.current += 1;
    const meu = pedidoDaContagem.current;
    setErroDaContagem(null);
    try {
      const { data } = await getContagem(ano);
      if (meu === pedidoDaContagem.current) setContagem({ ano, linhas: data });
    } catch (e) {
      if (e?.response?.status === 401) { semSessao(); return; }
      if (meu === pedidoDaContagem.current) setErroDaContagem(mensagemDeErro(e));
    }
  }, [ano, semSessao]);

  useEffect(() => { carregar(); }, [carregar]);
  useEffect(() => { if (vista === 'contagem') carregarContagem(); }, [vista, carregarContagem]);

  // Numa app instalada, voltar ao ecrã não remonta a página: relê-se ao voltar.
  useEffect(() => {
    const aoVoltar = () => {
      if (document.hidden) return;
      carregar();
      if (vista === 'contagem') carregarContagem();
    };
    document.addEventListener('visibilitychange', aoVoltar);
    return () => document.removeEventListener('visibilitychange', aoVoltar);
  }, [carregar, carregarContagem, vista]);

  // Na Semana as setas andam 7 dias; no resto, um mês (para hoje, se for o mês de hoje).
  const irPara = (passo) => {
    if (vista === 'semana') { setEscolhido(diaAoLado(escolhido, 7 * passo)); return; }
    const novo = mesAoLado(ano, mes, passo);
    setEscolhido(hoje.slice(0, 7) === chaveDoMes(novo.ano, novo.mes) ? hoje : isoDe(novo.ano, novo.mes, 1));
  };
  const escolherVista = (v) => { setVista(v); guardar(CHAVE_VISTA, v); };
  const escolherFiltro = (f) => { setFiltro(f); guardar(CHAVE_FILTRO, f); };
  const escolherLoja = (id) => { setLojaGuardada(id); guardar(CHAVE_LOJA, id || null); };

  // As lojas não dependem do mês: servem as da última leitura (as pastilhas não piscam ao mudar
  // de semana). Uma loja guardada que já não está entre elas conta como «Todas».
  const lojas = Object.values(respostas)[0]?.lojas || [];
  const loja = lojas.some((l) => l.id === lojaGuardada) ? lojaGuardada : '';

  const erroVisivel = erro || (vista === 'contagem' ? erroDaContagem : null);
  // Os números no ecrã são DESTES meses? Enquanto faltar um, esqueletos. O painel e o editar
  // usam o mês do dia escolhido (a grelha do painel é a desse mês); a Semana, os meses juntos.
  // O filtro de loja só muda o que se desenha: o painel recebe o mês inteiro (todas as lojas).
  const lidas = meses.split(' ').map((m) => respostas[m]);
  const prontos = lidas.every(Boolean);
  const desteMes = prontos ? respostas[chaveDoMes(ano, mes)] : null;
  const doMes = filtrarPorLoja(desteMes, loja);
  const daSemana = prontos && vista === 'semana' ? filtrarPorLoja(juntarMeses(lidas), loja) : null;

  const abrirPainel = (p) => {
    aberturas.current += 1;
    setPainel({ ...p, chave: aberturas.current });
  };
  const tapar = (b) => abrirPainel({
    modo: 'tapar', nomeDaLoja: b.nome,
    inicial: { datas: [b.data], location_id: b.location_id, inicio: b.inicio, fim: b.fim },
  });
  const editar = (idaId) => {
    const ida = (desteMes?.idas || []).find((i) => i.id === idaId);
    if (!ida) return;
    abrirPainel({
      modo: 'editar',
      inicial: {
        ida_id: ida.id, datas: [ida.data], location_id: ida.location_id, user_ids: [ida.user_id],
        inicio: ida.inicio, fim: ida.fim, nome: ida.nome,
      },
    });
  };
  // «+ Marcar ida» abre o painel vazio, com a loja a escolher (desenho, secção 4); as horas
  // vêm do horário da loja que se escolher (PainelIda). Fica o dia tocado e a pessoa por
  // omissão, como no Tapar. Com o filtro de loja, abre já nessa loja; as horas dela no dia
  // põe-nas o painel, com a mesma regra de quando se escolhe a loja lá dentro.
  const marcar = () => abrirPainel({
    modo: 'marcar',
    inicial: { datas: escolhido ? [escolhido] : [], location_id: loja, inicio: '', fim: '' },
  });
  const guardado = () => {
    setPainel(null);
    carregar();
    if (vista === 'contagem') carregarContagem();
  };

  const seta = 'h-11 w-11 shrink-0 inline-flex items-center justify-center rounded-lg active:bg-accent/60 '
    + 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

  return (
    <div className="min-h-[100dvh] bg-muted/30 pb-32">
      <header className="sticky top-0 z-20 bg-card border-b safe-area-inset-top">
        <div className="flex items-center gap-1 pl-1 pr-1 h-14">
          <BotaoMenu onClick={() => setMenu(true)} />
          <div className="min-w-0 flex-1">
            <h1 className="font-heading font-bold text-base leading-tight truncate first-letter:uppercase">
              {vista === 'semana' ? tituloDaSemana(escolhido) : tituloDoMes(ano, mes)}
            </h1>
            <p className="text-[11px] text-muted-foreground leading-tight truncate">
              {carregando ? 'A ler…' : 'Calendário das lojas'}
              {erroVisivel && <span className="text-destructive"> · falhou</span>}
            </p>
          </div>
          <button type="button" aria-label={vista === 'semana' ? 'Semana anterior' : 'Mês anterior'} onClick={() => irPara(-1)} className={seta}>
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button type="button" aria-label={vista === 'semana' ? 'Semana seguinte' : 'Mês seguinte'} onClick={() => irPara(1)} className={seta}>
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
        <div className="px-3 pb-2">
          <Calha>
            <Segmento activo={vista === 'semana'} onClick={() => escolherVista('semana')}>Semana</Segmento>
            <Segmento activo={vista === 'mes'} onClick={() => escolherVista('mes')}>Mês</Segmento>
            <Segmento activo={vista === 'lista'} onClick={() => escolherVista('lista')}>Lista</Segmento>
            <Segmento activo={vista === 'contagem'} onClick={() => escolherVista('contagem')}>Contagem</Segmento>
          </Calha>
        </div>
        {vista !== 'contagem' && lojas.length > 0 && (
          <FiltroDeLoja lojas={lojas} escolhida={loja} onEscolher={escolherLoja} />
        )}
      </header>

      <main className="px-3 pt-3 pb-6 max-w-2xl mx-auto">
        {erroVisivel && (
          <section role="alert" className="mb-3 rounded-2xl border border-destructive/40 bg-destructive/10 p-3 flex items-start gap-2.5">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="font-medium">Não foi possível ler agora.</p>
              <p className="text-sm text-muted-foreground mt-0.5 whitespace-pre-line break-words">{erroVisivel}</p>
            </div>
          </section>
        )}

        {vista === 'semana' && (!daSemana ? <Esqueleto /> : filtro === 'ferias'
          ? <FeriasDaSemana dados={daSemana} escolhido={escolhido} />
          : (
            <>
              <Semana dados={daSemana} filtro={filtro} escolhido={escolhido} onTocar={setEscolhido} />
              <Dia dados={daSemana} iso={escolhido} filtro={filtro} onTapar={tapar} onIda={editar} />
            </>
          ))}
        {vista === 'mes' && (
          <>
            <section className="rounded-2xl border bg-card p-2">
              <GrelhaDoMes
                ano={ano} mes={mes} hoje={hoje} escolhidos={escolhido ? [escolhido] : []} onTocar={setEscolhido}
                pontos={doMes ? diasComPonto(doMes, filtro) : []} corDoPonto={COR_DO_PONTO[filtro]}
                feriados={desteMes ? feriadosDoMes(desteMes) : []}
              />
            </section>
            {doMes
              ? <Dia dados={doMes} iso={escolhido} filtro={filtro} onTapar={tapar} onIda={editar} />
              : <Esqueleto />}
          </>
        )}
        {vista === 'lista' && (doMes
          ? <Lista dados={doMes} filtro={filtro} hoje={hoje} onTapar={tapar} onIda={editar} />
          : <Esqueleto />)}
        {vista === 'contagem' && (
          <Contagem linhas={contagem && contagem.ano === ano ? contagem.linhas : null} ano={ano} mes={mes} />
        )}

        {desteMes?.pode_marcar && desteMes.lojas.length > 0 && vista !== 'contagem' && (
          <button
            type="button" onClick={marcar}
            className="mt-4 w-full h-12 rounded-2xl border bg-card px-4 flex items-center justify-center gap-2 font-semibold
                       active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Plus className="h-5 w-5" />
            Marcar ida
          </button>
        )}
      </main>

      {vista !== 'contagem' && (
        <nav aria-label="Filtro" className="fixed bottom-0 left-0 right-0 z-30 bg-card border-t safe-area-inset-bottom">
          <div className="px-3 py-1.5 max-w-2xl mx-auto">
            <Calha>
              <Segmento activo={filtro === 'pessoal'} onClick={() => escolherFiltro('pessoal')}>Pessoal</Segmento>
              <Segmento activo={filtro === 'geral'} onClick={() => escolherFiltro('geral')}>Geral</Segmento>
              <Segmento activo={filtro === 'ferias'} onClick={() => escolherFiltro('ferias')}>Férias</Segmento>
            </Calha>
          </div>
        </nav>
      )}

      <MenuLateral aberto={menu} onFechar={() => setMenu(false)} actual="/bolso/calendario" />
      {painel && desteMes && (
        <PainelIda
          key={painel.chave} painel={painel} dados={desteMes} hoje={hoje}
          onFechar={() => setPainel(null)} onGuardado={guardado} onSemSessao={semSessao}
        />
      )}
    </div>
  );
}
