import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Receipt, Search, Loader2, HelpCircle, Printer, FileMinus, Copy, ArrowLeft,
  AlertTriangle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import {
  getDocumentosPos, getDocumentoPos, copiarDocumentoParaVenda, getVendaAberta,
  detalhesErroPos, eurosPos, avisoDoDocumento, momentoDaFaturaPos,
  resumoDosArtigosPos, casaComAPesquisaPos, razaoDeNaoCopiar,
  MSG_IMPRIMIR_BREVEMENTE, MSG_NOTA_DE_CREDITO_BREVEMENTE,
} from '@/lib/pos';

// O separador **Faturação**, ao lado do «Caixa» — a lista dos documentos já
// emitidos e a fatura aberta, com as três acções que o dono pediu do print do
// Vendus: Imprimir, Nota de Crédito e Copiar para a venda.
//
// Três regras mandam neste ficheiro, e são as do PosVenda:
//
//   1. **Os valores vêm SEMPRE do servidor.** Nem uma soma aqui. As linhas da
//      fatura, o mapa de imposto e os totais chegam somados de
//      `faturacao/documentos.py`, que por sua vez os vai buscar às MESMAS
//      funções que construíram as linhas entregues à AT. Se este ecrã somasse
//      colunas, o número que a operadora lê e o que está na fatura da AT podiam
//      divergir ao cêntimo — e seria a AT a ter razão.
//   2. **Nada desaparece em silêncio.** Um botão que ainda não faz nada fica à
//      vista, desligado e COM A RAZÃO escrita. Uma lista truncada diz que está
//      truncada. Um total que não bate com a soma das linhas grita.
//   3. **As decisões vivem em `lib/pos.js`**, não dentro do JSX — é lá que um
//      teste lhes chega e as pode EXECUTAR. Já aconteceu duas vezes neste
//      módulo um guarda verificar que certos nomes apareciam num ficheiro e
//      ficar verde com a decisão desligada por trás deles.

// A faixa do modo do documento (`tests` / desconhecido), com as mesmas cores do
// resto do POS. Em `normal` não desenha um pixel — ver `avisoDoDocumento`.
function FaixaDoDocumento({ documento }) {
  const aviso = avisoDoDocumento(documento);
  if (!aviso) return null;
  const cores = aviso.tom === 'perigo'
    ? 'bg-destructive text-destructive-foreground'
    : 'bg-amber-500 text-black';
  return (
    <div className={`flex items-start gap-2.5 rounded-lg px-3 py-2.5 ${cores}`}>
      <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
      <div className="min-w-0 text-sm">
        <p className="font-bold">{aviso.titulo}</p>
        <p className="mt-0.5">{aviso.texto}</p>
      </div>
    </div>
  );
}

// Uma linha da lista. O que lá está e porquê está escrito no backend
// (`documentos._documento_na_lista`): a HORA (com a data quando não é de hoje,
// porque «o cliente voltou amanhã» é o caso real), o NÚMERO impresso no talão
// que ele traz, o que LEVOU — que é como ela o reconhece quando ele não sabe o
// número — como PAGOU, e o TOTAL.
function LinhaDaLista({ documento, agora, onAbrir }) {
  const resumo = resumoDosArtigosPos(documento);
  const pagamentos = (documento.pagamentos || []).map((p) => p.nome).filter(Boolean);
  const aviso = avisoDoDocumento(documento);
  return (
    <button
      type="button"
      onClick={() => onAbrir(documento.id)}
      className="w-full text-left px-4 py-3 border-b hover:bg-muted/60 focus:bg-muted/60 focus:outline-none"
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium truncate">{documento.numero || '—'}</span>
        <span className="font-heading font-bold tabular-nums shrink-0">
          {eurosPos(documento.total)}
        </span>
      </div>
      <div className="flex items-baseline justify-between gap-3 mt-0.5">
        <span className="text-sm text-muted-foreground truncate">
          {documento.tem_venda === false
            ? 'A conta de origem já não está guardada'
            : (resumo || 'Sem artigos')}
        </span>
        <span className="text-sm text-muted-foreground tabular-nums shrink-0">
          {momentoDaFaturaPos(documento.emitido_em, agora)}
        </span>
      </div>
      {(pagamentos.length > 0 || aviso) && (
        <div className="flex items-center gap-2 mt-1">
          {pagamentos.length > 0 && (
            <span className="text-xs text-muted-foreground truncate">
              {pagamentos.join(' + ')}
            </span>
          )}
          {aviso && (
            <span className="text-xs font-bold text-destructive">{aviso.titulo}</span>
          )}
        </div>
      )}
    </button>
  );
}

// A tabela de artigos do print do Vendus: Produto · Preço/Uni. · Qtd. · Preço.
function TabelaDeArtigos({ linhas }) {
  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="grid grid-cols-[1fr_5.5rem_3rem_5.5rem] gap-2 px-3 h-9 items-center bg-muted text-xs uppercase tracking-wide text-muted-foreground">
        <span>Produto</span>
        <span className="text-right">Preço/Uni.</span>
        <span className="text-center">Qtd.</span>
        <span className="text-right">Preço</span>
      </div>
      {linhas.length === 0 ? (
        <p className="px-3 py-4 text-sm text-muted-foreground">
          Não há artigos para mostrar — a conta de origem desta fatura já não está guardada.
        </p>
      ) : linhas.map((linha, i) => (
        <div
          key={`${linha.titulo}-${i}`}
          className="grid grid-cols-[1fr_5.5rem_3rem_5.5rem] gap-2 px-3 py-2 items-baseline border-t text-sm"
        >
          <span className="break-words">
            {linha.titulo}
            {/* **O desconto, dito.** Sem esta linha, «€ 10,20 · 1 · € 9,94»
                lê-se como um erro de soma e quem confere o talão pára ali. O
                valor vem SOMADO do servidor — este ecrã não subtrai euros. */}
            {linha.desconto > 0 && (
              <span className="block text-xs text-muted-foreground tabular-nums">
                desconto −{eurosPos(linha.desconto)}
              </span>
            )}
          </span>
          <span className="text-right tabular-nums">{eurosPos(linha.preco_unitario)}</span>
          <span className="text-center tabular-nums">{linha.quantidade}</span>
          <span className="text-right tabular-nums font-medium">{eurosPos(linha.total)}</span>
        </div>
      ))}
    </div>
  );
}

// O mapa de imposto DESTE documento — Taxa · Base · IVA · Total, como no print.
// Vem inteiro do servidor (`mapa_imposto.mapa_de_imposto`, a MESMA função do Z)
// e o rodapé é a soma que ELE devolveu, nunca uma soma feita aqui: o número por
// baixo de uma tabela tem de ser a soma da tabela que está por cima dele, e não
// um segundo cálculo que pode não dar o mesmo.
function MapaDeImposto({ mapa, totais }) {
  if (!mapa || mapa.length === 0) return null;
  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="grid grid-cols-4 gap-2 px-3 h-9 items-center bg-muted text-xs uppercase tracking-wide text-muted-foreground">
        <span>Taxa</span>
        <span className="text-right">Base</span>
        <span className="text-right">IVA</span>
        <span className="text-right">Total</span>
      </div>
      {mapa.map((linha) => (
        <div
          key={String(linha.tax_id)}
          className="grid grid-cols-4 gap-2 px-3 py-2 items-baseline border-t text-sm tabular-nums"
        >
          {/* Uma taxa que o servidor não reconheceu vem com `taxa`, `base` e
              `iva` a `null` e o total preenchido — mostra-se o código tal e
              qual e "—" nas duas colunas do imposto, que é o que faz a última
              linha não fechar e alguém dar por ela. Inventar uma taxa aqui era
              o oposto da regra de ouro do `precos.py`. */}
          <span>{linha.taxa === null || linha.taxa === undefined
            ? `${linha.tax_id ?? '?'} (?)` : `${linha.taxa}%`}</span>
          <span className="text-right">{linha.base === null ? '—' : eurosPos(linha.base)}</span>
          <span className="text-right">{linha.iva === null ? '—' : eurosPos(linha.iva)}</span>
          <span className="text-right font-medium">{eurosPos(linha.total)}</span>
        </div>
      ))}
      <div className="grid grid-cols-4 gap-2 px-3 py-2 items-baseline border-t text-sm tabular-nums bg-muted/50 font-medium">
        <span>Total</span>
        <span className="text-right">{eurosPos(totais?.base)}</span>
        <span className="text-right">{eurosPos(totais?.iva)}</span>
        <span className="text-right">{eurosPos(totais?.total)}</span>
      </div>
    </div>
  );
}

// Um botão da coluna da direita que ainda não faz nada: à vista, desligado e
// com a razão por baixo. A mesma regra do menu Caixa (Abrir Gaveta, Modo de
// Formação) e do "Imprimir Pedido" do PosVenda.
function AccaoBrevemente({ icone: Icone, texto, porque }) {
  return (
    <div>
      <Button variant="outline" className="w-full h-12 justify-start" disabled>
        <Icone className="h-5 w-5 mr-2" />
        {texto}
        <span className="ml-auto text-[10px] uppercase tracking-wide">Brevemente</span>
      </Button>
      <p className="text-[11px] text-muted-foreground leading-snug mt-1.5">{porque}</p>
    </div>
  );
}

// A FATURA ABERTA, no desenho do print do Vendus.
function Fatura({ fatura, contaEmCurso, aCopiar, onCopiar, onVoltar }) {
  const naoCopiar = razaoDeNaoCopiar({ contaEmCurso, documento: fatura });
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onVoltar}>
          <ArrowLeft className="h-4 w-4 mr-1" /> Faturas
        </Button>
      </div>

      {/* O cabeçalho azul do print, com a referência ao centro. */}
      <div className="rounded-lg bg-primary text-primary-foreground px-4 py-3 text-center">
        <p className="font-heading font-bold text-2xl break-all">{fatura.numero || '—'}</p>
      </div>

      <FaixaDoDocumento documento={fatura} />

      <div className="grid sm:grid-cols-2 gap-4 text-sm">
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Documento</p>
          <p><span className="text-muted-foreground">Data:</span>{' '}
            {fatura.emitido_em
              ? new Date(fatura.emitido_em).toLocaleString('pt-PT')
              : '—'}
          </p>
          <p><span className="text-muted-foreground">Tipo:</span>{' '}
            {fatura.tipo === 'FS' ? 'Fatura Simplificada' : (fatura.tipo || '—')}
          </p>
          {/* O ATCUD por extenso, e não um "ok": é ele que o cliente (ou a
              contabilista) usa para procurar o documento do lado da AT, e um
              visto verde não se pode copiar para lado nenhum. */}
          <p className="break-all"><span className="text-muted-foreground">Código AT:</span>{' '}
            <span className="font-mono select-all">{fatura.atcud || '—'}</span>
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Cliente</p>
          <p>{fatura.cliente_nif
            ? <>NIF <span className="font-mono select-all">{fatura.cliente_nif}</span></>
            : 'Consumidor Final'}</p>
        </div>
      </div>

      <TabelaDeArtigos linhas={fatura.linhas || []} />

      <div className="grid sm:grid-cols-2 gap-4">
        <div className="border rounded-lg overflow-hidden self-start">
          <div className="grid grid-cols-2 gap-2 px-3 h-9 items-center bg-muted text-xs uppercase tracking-wide text-muted-foreground">
            <span>Pagamento</span>
            <span className="text-right">Total</span>
          </div>
          {(fatura.pagamentos || []).length === 0 ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">
              Sem pagamentos registados nesta conta.
            </p>
          ) : (fatura.pagamentos || []).map((p, i) => (
            <div key={`${p.nome}-${i}`} className="grid grid-cols-2 gap-2 px-3 py-2 border-t text-sm">
              <span>{p.nome || '—'}</span>
              <span className="text-right tabular-nums font-medium">{eurosPos(p.valor)}</span>
            </div>
          ))}
        </div>
        <MapaDeImposto mapa={fatura.mapa_imposto} totais={fatura.totais_imposto} />
      </div>

      {/* **O total é o do DOCUMENTO** — o que a AT tem. Quando a soma das
          linhas não bate com ele ao cêntimo, isso não se esconde: nunca devia
          acontecer, e é precisamente por isso que tem de aparecer. */}
      {fatura.total_divergente && (
        <div className="flex items-start gap-2.5 rounded-lg bg-destructive text-destructive-foreground px-3 py-2.5">
          <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
          <div className="min-w-0 text-sm">
            <p className="font-bold">O total desta fatura não bate com a soma das linhas.</p>
            <p className="mt-0.5">
              O documento entregue à Autoridade Tributária diz {eurosPos(fatura.total)} e as
              linhas somam {eurosPos(fatura.total_das_linhas)}. Não entregue nada ao cliente
              sem falar com o gestor.
            </p>
          </div>
        </div>
      )}

      <div className="bg-primary text-primary-foreground px-4 py-3 rounded-lg flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold uppercase tracking-wide">Total</span>
        <span className="font-heading font-bold text-3xl tabular-nums">
          {eurosPos(fatura.total)}
        </span>
      </div>

      <Separator />

      {/* A coluna de acções do print — só as três que o dono pediu. */}
      <div className="space-y-3">
        <AccaoBrevemente
          icone={Printer}
          texto="Imprimir"
          porque={MSG_IMPRIMIR_BREVEMENTE}
        />
        <AccaoBrevemente
          icone={FileMinus}
          texto="Nota de Crédito"
          porque={MSG_NOTA_DE_CREDITO_BREVEMENTE}
        />
        <div>
          <Button
            className="w-full h-12 justify-start"
            onClick={onCopiar}
            disabled={!!naoCopiar || aCopiar}
          >
            {aCopiar
              ? <Loader2 className="h-5 w-5 mr-2 animate-spin" />
              : <Copy className="h-5 w-5 mr-2" />}
            Copiar para a venda
          </Button>
          {/* A razão fica À VISTA por cima do dedo, e não escondida num
              `title` — a operadora tem de a LER antes do toque, não descobrir
              depois de esperar por um 409. */}
          <p className="text-[11px] text-muted-foreground leading-snug mt-1.5">
            {naoCopiar || 'Abre uma conta nova com os mesmos artigos e as mesmas '
              + 'personalizações, aos preços de hoje.'}
          </p>
        </div>
      </div>
    </div>
  );
}

export default function PosFaturacao({ caixa, onContaCopiada }) {
  const [aberto, setAberto] = useState(false);
  const [lista, setLista] = useState(null);
  const [erro, setErro] = useState(null);
  const [pesquisa, setPesquisa] = useState('');
  const [abertaId, setAbertaId] = useState(null);
  const [fatura, setFatura] = useState(null);
  const [erroFatura, setErroFatura] = useState(null);
  const [contaEmCurso, setContaEmCurso] = useState(null);
  const [aCopiar, setACopiar] = useState(false);
  // O instante em que a lista foi lida — é a referência de «hoje» para as
  // horas. Fixado na leitura e não `new Date()` a cada render: senão o "Ontem"
  // de uma fatura mudava sozinho à meia-noite com o painel aberto.
  const [agora, setAgora] = useState(() => new Date());

  const caixaId = caixa?.id;

  const carregar = useCallback(async () => {
    setLista(null);
    setErro(null);
    setAgora(new Date());
    try {
      const { data } = await getDocumentosPos();
      setLista(data);
    } catch (error) {
      setErro(detalhesErroPos(error, 'Não foi possível ler as faturas.').mensagem);
    }
  }, []);

  // A conta em curso deste posto — perguntada ao SERVIDOR e não deduzida de
  // nada que o painel saiba. É ela que decide se «Copiar para a venda» está
  // vivo, e é a mesma pergunta que a porta faz (`GET /pos/venda/aberta`).
  // Relida sempre que se abre o painel: uma resposta guardada de há dez minutos
  // dizia «o balcão está livre» com um cliente a meio.
  const lerContaEmCurso = useCallback(async () => {
    if (!caixaId) return;
    try {
      const { data } = await getVendaAberta(caixaId);
      setContaEmCurso(data || null);
    } catch (error) {
      // Sem resposta não se aprendeu nada, e o lado seguro é o que NÃO promete
      // que o balcão está livre: o botão fica morto e diz porquê. É o servidor
      // que recusa de qualquer forma (409), mas prometer aqui que dá era
      // convidar ao toque que vai falhar.
      setContaEmCurso({ id: '?', desconhecida: true });
    }
  }, [caixaId]);

  useEffect(() => {
    if (!aberto) return;
    carregar();
    lerContaEmCurso();
  }, [aberto, carregar, lerContaEmCurso]);

  useEffect(() => {
    if (!abertaId) { setFatura(null); setErroFatura(null); return undefined; }
    let vivo = true;
    setFatura(null);
    setErroFatura(null);
    getDocumentoPos(abertaId)
      .then(({ data }) => { if (vivo) setFatura(data); })
      .catch((error) => {
        if (!vivo) return;
        setErroFatura(detalhesErroPos(error, 'Não foi possível abrir a fatura.').mensagem);
      });
    return () => { vivo = false; };
  }, [abertaId]);

  const copiar = useCallback(async () => {
    if (!fatura || aCopiar) return;
    setACopiar(true);
    try {
      const { data } = await copiarDocumentoParaVenda(fatura.id, caixaId);
      const falhados = data?.nao_copiados || [];
      if (falhados.length > 0) {
        // Nunca um sucesso liso quando faltou alguma coisa: a operadora leva o
        // pedido à cozinha e o cliente recebe menos do que pediu.
        toast.warning(`Conta aberta sem ${falhados.length} ${
          falhados.length === 1 ? 'artigo' : 'artigos'}: ${falhados.join('; ')}`);
      } else {
        toast.success('Conta nova aberta com os artigos desta fatura.');
      }
      setAberto(false);
      setAbertaId(null);
      if (onContaCopiada) onContaCopiada();
    } catch (error) {
      const { mensagem } = detalhesErroPos(error, 'Não foi possível copiar esta fatura.');
      toast.error(mensagem);
      // A recusa mais provável é a porta (409, o posto está ocupado) — relê-se
      // a conta em curso para o botão passar a estar morto com a razão à vista,
      // em vez de continuar a convidar ao mesmo toque.
      lerContaEmCurso();
    } finally {
      setACopiar(false);
    }
  }, [fatura, aCopiar, caixaId, onContaCopiada, lerContaEmCurso]);

  const documentos = (lista?.documentos || []).filter((d) => casaComAPesquisaPos(d, pesquisa));

  return (
    <>
      <Button
        variant="outline"
        size="lg"
        className="h-11"
        onClick={() => { setAbertaId(null); setAberto(true); }}
      >
        <Receipt className="h-4 w-4 mr-1" /> Faturação
      </Button>

      <Dialog open={aberto} onOpenChange={(v) => { if (!v) { setAberto(false); setAbertaId(null); } }}>
        <DialogContent className="max-w-3xl max-h-[92vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{abertaId ? 'Fatura' : 'Faturação'}</DialogTitle>
          </DialogHeader>

          {abertaId ? (
            erroFatura ? (
              <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{erroFatura}</span>
              </div>
            ) : !fatura ? (
              <div className="flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                <span>A abrir a fatura…</span>
              </div>
            ) : (
              <Fatura
                fatura={fatura}
                contaEmCurso={contaEmCurso}
                aCopiar={aCopiar}
                onCopiar={copiar}
                onVoltar={() => setAbertaId(null)}
              />
            )
          ) : (
            <>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  value={pesquisa}
                  onChange={(e) => setPesquisa(e.target.value)}
                  placeholder="Número, valor, artigo ou pagamento"
                  className="pl-9 h-11"
                />
              </div>

              {erro ? (
                <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                  <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{erro}</span>
                </div>
              ) : !lista ? (
                <div className="flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                  <span>A ler as faturas…</span>
                </div>
              ) : (
                <>
                  <div className="border rounded-lg overflow-hidden">
                    {documentos.length === 0 ? (
                      <p className="px-4 py-6 text-sm text-muted-foreground text-center">
                        {(lista.documentos || []).length === 0
                          ? 'Ainda não há nenhuma fatura emitida nesta loja.'
                          : 'Nenhuma fatura destas bate com o que escreveu.'}
                      </p>
                    ) : documentos.map((d) => (
                      <LinhaDaLista key={d.id} documento={d} agora={agora} onAbrir={setAbertaId} />
                    ))}
                  </div>
                  {/* **Uma lista truncada que não se assume mente sobre o que
                      não encontrou**: a operadora procura, não encontra, e
                      conclui que a fatura não existe. O número vem do servidor
                      (`limite`), não escrito aqui — duas cópias do mesmo tecto
                      acabam sempre com o ecrã a prometer um alcance que já não
                      é o real. */}
                  <p className="text-[11px] text-muted-foreground leading-snug">
                    Faturas desta loja, da mais recente para a mais antiga.
                    {lista.ha_mais
                      ? ` Só as ${lista.limite} mais recentes — as mais antigas ficam de fora `
                        + 'desta lista e procuram-se no Vendus.'
                      : ' Estão aqui todas.'}
                  </p>
                </>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
