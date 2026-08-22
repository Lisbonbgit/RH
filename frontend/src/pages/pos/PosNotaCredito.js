import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, AlertTriangle, FileMinus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import {
  getNotaCreditoPos, preVisualizarNotaCreditoPos, emitirNotaCreditoPos,
  getTiposPagamentoPos, detalhesErroPos, eurosPos,
  quantidadeDaNotaPos, linhasDaNotaPos, linhaDaNotaCreditavel,
  razaoDeNaoEmitirNotaCredito, efeitoNaGavetaPos, avisoDoMeioDeDevolucaoPos,
} from '@/lib/pos';

// O ecrã da **NOTA DE CRÉDITO**, no desenho do print do POS do Vendus que o
// dono mandou: cabeçalho laranja, o documento original e o cliente em duas
// colunas, a tabela dos artigos com uma caixa por linha e a quantidade
// editável, o mapa de imposto das linhas escolhidas, o motivo e a devolução, e
// as duas acções empilhadas à direita.
//
// **A coluna «Stock» do print não existe aqui** — é do Vendus, e nós não temos
// stock. Nem o «Documento Manual» nem a caixa «Documentos Associados».
//
// As três regras do `PosFaturacao` valem inteiras, e aqui a primeira vale a
// dobrar:
//
//   1. **Nem uma soma neste ficheiro.** O subtotal, o total e o mapa de imposto
//      das linhas seleccionadas vêm de `POST …/nota-credito/pre-visualizar` a
//      cada mudança da selecção. Um browser a somar euros ao lado de um
//      servidor a somar cêntimos era a divergência garantida — com a diferença
//      a aparecer num documento fiscal REAL entregue à Autoridade Tributária.
//   2. **Nada desaparece em silêncio.** Uma linha já toda creditada fica na
//      lista, morta e com o porquê à vista: some-la fazia a operadora procurar
//      o artigo que o cliente traz na mão, não o encontrar, e concluir que a
//      fatura não era aquela.
//   3. **As decisões vivem em `lib/pos.js`** — `razaoDeNaoEmitirNotaCredito`,
//      `quantidadeDaNotaPos`, `linhasDaNotaPos`, `efeitoNaGavetaPos`. É lá que
//      um guarda lhes chega e as pode EXECUTAR.

// **A identidade da devolução, gerada UMA vez por janela.** É dela que o
// servidor deriva a referência externa da nota (`pos-{loja}-{sessão}-nc-{id}`),
// e é ela que torna o segundo toque no botão inofensivo: a mesma intenção duas
// vezes é apanhada pelo índice único antes de falar com o Vendus. Uma janela
// nova é outra intenção — que é o que deixa existir a segunda nota parcial da
// mesma fatura.
function novaIntencao() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  // Sem `crypto.randomUUID` (um WebView antigo do PC da loja) — a forma do
  // UUID tem de se manter, porque o servidor a valida: um identificador fora
  // do formato podia colidir com a intenção de outra loja.
  return 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () =>
    Math.floor(Math.random() * 16).toString(16));
}

// O cabeçalho LARANJA do print: «Nota de Crédito - FT 05P2026/1824».
function CabecalhoDaNota({ numeroOriginal }) {
  return (
    <div className="rounded-lg bg-amber-500 text-black px-4 py-3 text-center">
      <p className="font-heading font-bold text-xl break-all">
        Nota de Crédito - {numeroOriginal || '—'}
      </p>
    </div>
  );
}

// A tabela dos artigos. Uma caixa no cabeçalho (marca/desmarca tudo) e uma por
// linha; a quantidade é editável, com o MÁXIMO à vista ao lado — como no print.
function ArtigosDaNota({ linhas, escolhas, onLinha, onTodas }) {
  const creditaveis = linhas.filter(linhaDaNotaCreditavel);
  const todasMarcadas = creditaveis.length > 0
    && creditaveis.every((li) => escolhas[li.indice]?.marcada);
  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="grid grid-cols-[1.75rem_1fr_7rem_5.5rem_5.5rem] gap-2 px-3 h-9 items-center bg-muted text-xs uppercase tracking-wide text-muted-foreground">
        <input
          type="checkbox"
          aria-label="Marcar todos os artigos"
          className="h-4 w-4"
          checked={todasMarcadas}
          disabled={creditaveis.length === 0}
          onChange={(e) => onTodas(e.target.checked)}
        />
        <span>Produto</span>
        <span className="text-center">Qtd.</span>
        <span className="text-right">Preço/Uni.</span>
        <span className="text-right">Total</span>
      </div>
      {linhas.length === 0 ? (
        <p className="px-3 py-4 text-sm text-muted-foreground">
          Esta fatura não tem artigos para creditar.
        </p>
      ) : linhas.map((linha) => {
        const podeCreditar = linhaDaNotaCreditavel(linha);
        const escolha = escolhas[linha.indice] || {};
        return (
          <div
            key={linha.indice}
            className="grid grid-cols-[1.75rem_1fr_7rem_5.5rem_5.5rem] gap-2 px-3 py-2 items-center border-t text-sm"
          >
            <input
              type="checkbox"
              aria-label={`Creditar ${linha.titulo}`}
              className="h-4 w-4"
              checked={!!escolha.marcada}
              disabled={!podeCreditar}
              onChange={(e) => onLinha(linha, { marcada: e.target.checked })}
            />
            <span className="break-words">
              {linha.titulo}
              {/* **A linha já creditada explica-se.** Sem esta frase, a caixa
                  morta lê-se como uma avaria do ecrã. */}
              {!podeCreditar && (
                <span className="block text-xs text-destructive">
                  Já creditado por inteiro numa nota anterior.
                </span>
              )}
            </span>
            <span className="flex items-center justify-center gap-1.5">
              <Input
                type="text"
                inputMode="decimal"
                aria-label={`Quantidade a creditar de ${linha.titulo}`}
                className="h-9 w-16 text-center tabular-nums"
                disabled={!podeCreditar}
                value={escolha.quantidade ?? ''}
                onChange={(e) => onLinha(linha, {
                  marcada: true, quantidade: e.target.value,
                })}
              />
              {/* O máximo à vista ao lado, como no print (`1` editável e `1` de
                  limite). Quem RECUSA é o servidor — isto é só a operadora a
                  saber de antemão. */}
              <span className="text-xs text-muted-foreground tabular-nums shrink-0">
                / {linha.disponivel}
              </span>
            </span>
            <span className="text-right tabular-nums">{eurosPos(linha.preco_unitario)}</span>
            <span className="text-right tabular-nums font-medium">{eurosPos(linha.total)}</span>
          </div>
        );
      })}
    </div>
  );
}

// O mapa de imposto das linhas SELECCIONADAS, e os totais ao lado — os dois
// vindos do servidor, do mesmo `pre-visualizar`.
function DinheiroDaNota({ resumo, aSomar }) {
  const mapa = resumo?.mapa_imposto || [];
  return (
    <div className="grid sm:grid-cols-2 gap-4">
      <div className="border rounded-lg overflow-hidden self-start">
        <div className="grid grid-cols-4 gap-2 px-3 h-9 items-center bg-muted text-xs uppercase tracking-wide text-muted-foreground">
          <span>Taxa</span>
          <span className="text-right">Base</span>
          <span className="text-right">IVA</span>
          <span className="text-right">Total</span>
        </div>
        {mapa.length === 0 ? (
          <p className="px-3 py-2 text-sm text-muted-foreground">
            Marque os artigos para ver o imposto a devolver.
          </p>
        ) : mapa.map((linha) => (
          <div
            key={String(linha.tax_id)}
            className="grid grid-cols-4 gap-2 px-3 py-2 items-baseline border-t text-sm tabular-nums"
          >
            <span>{linha.taxa === null || linha.taxa === undefined
              ? `${linha.tax_id ?? '?'} (?)` : `${linha.taxa}%`}</span>
            <span className="text-right">{linha.base === null ? '—' : eurosPos(linha.base)}</span>
            <span className="text-right">{linha.iva === null ? '—' : eurosPos(linha.iva)}</span>
            <span className="text-right font-medium">{eurosPos(linha.total)}</span>
          </div>
        ))}
      </div>

      <div className="space-y-2 self-start">
        <div className="flex items-baseline justify-between gap-3 px-3 py-2 border rounded-lg text-sm">
          <span className="text-muted-foreground uppercase tracking-wide text-xs">Subtotal</span>
          <span className="tabular-nums font-medium">{eurosPos(resumo?.subtotal ?? 0)}</span>
        </div>
        <div className="flex items-baseline justify-between gap-3 bg-amber-500 text-black px-4 py-3 rounded-lg">
          <span className="text-sm font-semibold uppercase tracking-wide">Total</span>
          <span className="font-heading font-bold text-2xl tabular-nums">
            {aSomar ? '…' : eurosPos(resumo?.total ?? 0)}
          </span>
        </div>
        {/* **A prova de que este número não foi somado aqui.** Vale mais do
            que parece: quem vier a este ficheiro daqui a um ano vê logo que a
            tentação de somar as linhas no browser já foi recusada uma vez. */}
        <p className="text-[11px] text-muted-foreground leading-snug">
          Somado pelo servidor, em cêntimos — é o valor que vai na nota de
          crédito entregue à Autoridade Tributária.
        </p>
      </div>
    </div>
  );
}

export default function PosNotaCredito({ documento, onFechar, onEmitida, caixaId }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [escolhas, setEscolhas] = useState({});
  const [motivo, setMotivo] = useState('');
  const [tipos, setTipos] = useState([]);
  const [tipoId, setTipoId] = useState('');
  const [resumo, setResumo] = useState(null);
  const [aSomar, setASomar] = useState(false);
  const [aEmitir, setAEmitir] = useState(false);
  const [erroDaSelecao, setErroDaSelecao] = useState(null);
  const [emitida, setEmitida] = useState(null);
  // A intenção nasce com a janela e NÃO muda enquanto ela estiver aberta: é
  // isso que faz o segundo toque no botão ser o mesmo toque. `useRef` e não
  // `useState` de propósito — um re-render não pode gerar outra.
  const intencao = useRef(novaIntencao());
  // **A tranca do duplo toque, e é um `useRef` de propósito.** O `aEmitir` do
  // estado desliga o botão, mas só depois de o React voltar a desenhar — dois
  // toques rápidos no mesmo dedo correm os DOIS com o mesmo `aEmitir` a
  // `false` fechado no callback, e saíam dois `POST`. O servidor apanha-os (é
  // a mesma intenção, e o índice único torna o segundo inofensivo), mas o
  // segundo volta 409 «esta nota já está a ser emitida» e pinta de vermelho um
  // ecrã em que a nota SAIU. A tranca é lida e escrita no mesmo instante do
  // toque, sem esperar por render nenhum.
  const aEmitirAgora = useRef(false);

  const documentoId = documento?.id;

  useEffect(() => {
    let vivo = true;
    setDados(null);
    setErro(null);
    getNotaCreditoPos(documentoId)
      .then(({ data }) => { if (vivo) setDados(data); })
      .catch((error) => {
        if (!vivo) return;
        setErro(detalhesErroPos(
          error, 'Não foi possível preparar a nota de crédito.').mensagem);
      });
    getTiposPagamentoPos()
      .then(({ data }) => { if (vivo) setTipos(data || []); })
      .catch(() => { if (vivo) setTipos([]); });
    return () => { vivo = false; };
  }, [documentoId]);

  const linhas = useMemo(() => dados?.linhas || [], [dados]);
  const escolhidas = useMemo(
    () => linhasDaNotaPos(linhas, escolhas), [linhas, escolhas]);

  // **O dinheiro, a cada mudança da selecção — e sempre do servidor.**
  // A chave é o JSON das linhas escolhidas: sem ela, uma nova referência de
  // array a cada render disparava um pedido por render.
  const chaveDaSelecao = JSON.stringify(escolhidas);
  useEffect(() => {
    if (!documentoId || emitida) return undefined;
    const pedidas = JSON.parse(chaveDaSelecao);
    let vivo = true;
    setASomar(true);
    preVisualizarNotaCreditoPos(documentoId, pedidas)
      .then(({ data }) => {
        if (!vivo) return;
        setResumo(data);
        setErroDaSelecao(null);
      })
      .catch((error) => {
        if (!vivo) return;
        // **A recusa aparece enquanto a operadora escolhe**, e não depois de
        // carregar em EMITIR com o cliente à frente. O total volta a zero: um
        // total antigo por baixo de uma selecção recusada era o pior dos dois
        // mundos.
        setResumo(null);
        setErroDaSelecao(detalhesErroPos(
          error, 'Não foi possível somar esta selecção.').mensagem);
      })
      .finally(() => { if (vivo) setASomar(false); });
    return () => { vivo = false; };
  }, [documentoId, chaveDaSelecao, emitida]);

  const mexerLinha = useCallback((linha, mudanca) => {
    setEscolhas((antes) => {
      const atual = antes[linha.indice] || {};
      const seguinte = { ...atual, ...mudanca };
      if (seguinte.marcada && (seguinte.quantidade === undefined
        || seguinte.quantidade === '')) {
        // Marcar uma linha propõe o que ela ainda tem — é o que o print faz
        // (`1` editável contra `1` de limite) e o gesto mais provável.
        seguinte.quantidade = String(linha.disponivel);
      }
      if (mudanca.quantidade !== undefined) {
        seguinte.quantidade = String(
          quantidadeDaNotaPos(mudanca.quantidade, linha.disponivel));
      }
      return { ...antes, [linha.indice]: seguinte };
    });
  }, []);

  const mexerTodas = useCallback((marcar) => {
    setEscolhas(() => {
      if (!marcar) return {};
      const seguinte = {};
      linhas.filter(linhaDaNotaCreditavel).forEach((li) => {
        seguinte[li.indice] = { marcada: true, quantidade: String(li.disponivel) };
      });
      return seguinte;
    });
  }, [linhas]);

  const tipoEscolhido = tipos.find((t) => t.id === tipoId) || null;
  const avisoDoMeio = avisoDoMeioDeDevolucaoPos({
    tipo: tipoEscolhido,
    pagamentos: dados?.pagamentos,
    // O total vem do servidor (`pre-visualizar`), como todo o dinheiro deste
    // ecrã — nunca de uma soma feita aqui.
    total: resumo?.total,
  });
  const naoEmitir = razaoDeNaoEmitirNotaCredito({
    linhas: escolhidas, motivo, tipoPagamentoId: tipoId, aEmitir,
  }) || (erroDaSelecao ? 'Corrija a selecção antes de emitir.' : null);

  const emitir = useCallback(async () => {
    if (aEmitirAgora.current) return;
    aEmitirAgora.current = true;
    setAEmitir(true);
    try {
      const { data } = await emitirNotaCreditoPos(documentoId, {
        intencao_id: intencao.current,
        caixa_id: caixaId,
        motivo: motivo.trim(),
        tipo_pagamento_id: tipoId,
        linhas: escolhidas,
      });
      setEmitida(data);
      toast.success(`Nota de crédito ${data.numero || ''} emitida.`);
      if (onEmitida) onEmitida(data);
    } catch (error) {
      const { mensagem } = detalhesErroPos(
        error, 'Não foi possível emitir a nota de crédito.');
      toast.error(mensagem);
      setErro(mensagem);
    } finally {
      aEmitirAgora.current = false;
      setAEmitir(false);
    }
  }, [documentoId, caixaId, motivo, tipoId, escolhidas, onEmitida]);

  // --- Depois de emitir: o que a operadora tem de fazer a seguir ------------
  if (emitida) {
    const efeito = efeitoNaGavetaPos(emitida.devolucao);
    return (
      <div className="space-y-4">
        <div className="rounded-lg bg-amber-500 text-black px-4 py-3 text-center">
          <p className="font-heading font-bold text-xl break-all">
            {emitida.numero || 'Nota de Crédito'}
          </p>
          <p className="text-sm mt-0.5">corrige {emitida.numero_origem || '—'}</p>
        </div>
        <div className="flex items-baseline justify-between gap-3 px-4 py-3 rounded-lg bg-muted">
          <span className="text-sm font-semibold uppercase tracking-wide">Devolvido</span>
          <span className="font-heading font-bold text-2xl tabular-nums">
            {eurosPos(emitida.total)}
          </span>
        </div>
        {/* **O que fazer ao dinheiro, dito em letras grandes.** É a única
            instrução que separa a gaveta certa da gaveta errada, e o dono
            resumiu-a assim: «se a nota de crédito estiver lá que a devolução
            foi em dinheiro, sim sai da gaveta. se não, sai dos outros
            lugares.» */}
        {efeito && (
          <div className="rounded-lg border-2 border-amber-500 px-4 py-3 text-sm font-medium">
            {efeito}
          </div>
        )}
        {emitida.total_divergente && (
          <div className="flex items-start gap-2.5 rounded-lg bg-destructive text-destructive-foreground px-3 py-2.5">
            <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
            <div className="min-w-0 text-sm">
              <p className="font-bold">
                O total desta nota não bate com a soma das linhas.
              </p>
              <p className="mt-0.5">
                O documento entregue à Autoridade Tributária diz {eurosPos(emitida.total)} e
                as linhas somam {eurosPos(emitida.total_das_linhas)}. Não devolva nada ao
                cliente sem falar com o gestor.
              </p>
            </div>
          </div>
        )}
        <p className="text-xs text-muted-foreground break-all">
          Código AT: <span className="font-mono select-all">{emitida.atcud || '—'}</span>
        </p>
        <Button className="w-full h-12" onClick={onFechar}>Fechar</Button>
      </div>
    );
  }

  if (erro && !dados) {
    return (
      <div className="space-y-3">
        <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{erro}</span>
        </div>
        <Button variant="outline" className="w-full h-12" onClick={onFechar}>Cancelar</Button>
      </div>
    );
  }

  if (!dados) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin shrink-0" />
        <span>A preparar a nota de crédito…</span>
      </div>
    );
  }

  const original = dados.documento || {};

  return (
    <div className="space-y-4">
      <CabecalhoDaNota numeroOriginal={original.numero} />

      {/* As duas colunas do print: o documento original e o cliente. */}
      <div className="grid sm:grid-cols-2 gap-4 text-sm">
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Documento Original
          </p>
          <p className="flex items-center gap-2">
            <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-bold">
              {original.tipo || '—'}
            </span>
            <span className="break-all font-medium">{original.numero || '—'}</span>
          </p>
          <p><span className="text-muted-foreground">Data:</span>{' '}
            {original.emitido_em
              ? new Date(original.emitido_em).toLocaleDateString('pt-PT')
              : '—'}
          </p>
          <p><span className="text-muted-foreground">Tipo:</span>{' '}
            {original.tipo === 'FS' ? 'Fatura Simplificada' : (original.tipo || '—')}
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Cliente</p>
          <p>{dados.cliente_nif
            ? <>NIF <span className="font-mono select-all">{dados.cliente_nif}</span></>
            : 'Consumidor Final - NIF ---------'}</p>
        </div>
      </div>

      {/* **As notas anteriores desta fatura, à vista.** A operadora tem de
          saber que o cliente já cá veio — e que documento levou. */}
      {(dados.notas_anteriores || []).length > 0 && (
        <div className="rounded-lg border px-3 py-2 text-sm space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Esta fatura já foi creditada
          </p>
          {dados.notas_anteriores.map((n) => (
            <p key={n.id} className="flex items-baseline justify-between gap-3">
              <span className="truncate">
                {n.numero || 'Sem número'}
                {n.estado !== 'emitida' && (
                  <span className="ml-1.5 text-destructive font-bold">
                    {n.estado === 'incerta'
                      ? 'POR CONFIRMAR NO VENDUS'
                      : String(n.estado || '').toUpperCase()}
                  </span>
                )}
              </span>
              <span className="tabular-nums shrink-0">{eurosPos(n.total)}</span>
            </p>
          ))}
        </div>
      )}

      {/* **Como a fatura foi PAGA, e quanto de cada meio ainda não voltou.**
          O dono disse «a devolução segue o meio de pagamento» — e até aqui a
          operadora escolhia o meio sem ver nenhum destes números. Uma fatura
          de 11,29 € paga 5,00 em dinheiro e 6,29 em Multibanco deixava
          devolver 9,85 € da GAVETA, que ficava abaixo do fundo inicial. */}
      {(dados.pagamentos || []).length > 0 && (
        <div className="rounded-lg border px-3 py-2 text-sm space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Esta fatura foi paga assim
          </p>
          {dados.pagamentos.map((p) => (
            <p
              key={p.tipo_pagamento_id || p.nome}
              className="flex items-baseline justify-between gap-3"
            >
              <span className="truncate">{p.nome || '—'}</span>
              <span className="tabular-nums shrink-0">
                {eurosPos(p.recebido)}
                {p.devolvido > 0 && (
                  <span className="ml-1.5 text-muted-foreground">
                    (já devolvido {eurosPos(p.devolvido)} — sobra {eurosPos(p.disponivel)})
                  </span>
                )}
              </span>
            </p>
          ))}
        </div>
      )}

      <ArtigosDaNota
        linhas={linhas}
        escolhas={escolhas}
        onLinha={mexerLinha}
        onTodas={mexerTodas}
      />

      {erroDaSelecao && (
        <div className="flex items-start gap-2.5 rounded-lg bg-destructive text-destructive-foreground px-3 py-2.5 text-sm">
          <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
          <span>{erroDaSelecao}</span>
        </div>
      )}

      <DinheiroDaNota resumo={resumo} aSomar={aSomar} />

      <Separator />

      {/* Os dois campos lado a lado do print. */}
      <div className="grid sm:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label
            className="text-xs uppercase tracking-wide text-muted-foreground"
            htmlFor="nc-motivo"
          >
            Motivo para emissão da Nota de Crédito
          </label>
          <Input
            id="nc-motivo"
            value={motivo}
            maxLength={200}
            onChange={(e) => setMotivo(e.target.value)}
            placeholder="Ex.: cliente devolveu o açaí, veio com a fruta trocada"
            className="h-11"
          />
        </div>
        <div className="space-y-1.5">
          <label
            className="text-xs uppercase tracking-wide text-muted-foreground"
            htmlFor="nc-devolucao"
          >
            Devolução do Valor
          </label>
          <select
            id="nc-devolucao"
            value={tipoId}
            onChange={(e) => setTipoId(e.target.value)}
            className="w-full h-11 rounded-md border bg-background px-3 text-sm"
          >
            <option value="">Escolha por onde devolve…</option>
            {tipos.map((t) => (
              <option key={t.id} value={t.id} disabled={t.pronto === false}>
                {t.nome}{t.pronto === false ? ' — sem ligação ao Vendus' : ''}
              </option>
            ))}
          </select>
          {/* **O efeito na gaveta, ANTES de emitir.** É a diferença entre a
              operadora tirar dinheiro da gaveta e não tirar. */}
          <p className="text-[11px] text-muted-foreground leading-snug">
            {efeitoNaGavetaPos(tipoEscolhido)
              || 'Em dinheiro sai da gaveta e o fecho conta com isso; nos outros '
                + 'meios fica registada aí e a gaveta não mexe.'}
          </p>
          {/* **A devolução maior do que o que a fatura recebeu neste meio.**
              Ninguém a recusa (ver `pagamentos_da_fatura` no servidor) — mas
              a operadora tem de a LER antes do toque, com o número que vai
              faltar à gaveta. */}
          {avisoDoMeio && (
            <div className="flex items-start gap-2.5 rounded-lg bg-destructive text-destructive-foreground px-3 py-2 text-sm">
              <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
              <span>{avisoDoMeio}</span>
            </div>
          )}
        </div>
      </div>

      <Separator />

      {/* As duas acções empilhadas à direita do print. Sem «Documento Manual»
          e sem «Documentos Associados» — não os fazemos. */}
      <div className="space-y-3">
        <div>
          <Button
            className="w-full h-12 justify-start bg-amber-500 text-black hover:bg-amber-600"
            onClick={emitir}
            disabled={!!naoEmitir}
          >
            {aEmitir
              ? <Loader2 className="h-5 w-5 mr-2 animate-spin" />
              : <FileMinus className="h-5 w-5 mr-2" />}
            Emitir Nota de Crédito
          </Button>
          {/* A razão fica À VISTA por cima do dedo, e não escondida num
              `title`: a operadora tem de a LER antes do toque. */}
          <p className="text-[11px] text-muted-foreground leading-snug mt-1.5">
            {naoEmitir
              || 'Emite um documento fiscal REAL, entregue à Autoridade '
                + 'Tributária. Não se desfaz.'}
          </p>
        </div>
        <Button variant="outline" className="w-full h-12 justify-start" onClick={onFechar}>
          <X className="h-5 w-5 mr-2" /> Cancelar
        </Button>
      </div>
    </div>
  );
}
