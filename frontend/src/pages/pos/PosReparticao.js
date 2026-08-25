import React, { useState } from 'react';
import {
  ArrowLeft, Ban, CheckCircle2, Coins, Divide, Loader2, Receipt, Scissors, Trash2, Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle,
  AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { centimos, contasDaLinha, eurosPos as euros } from '@/lib/pos';

// **As partes por cobrar de uma conta repartida.** Quem falta pagar, quanto
// falta receber, e as duas coisas que se fazem a uma parte: cobrá-la ou
// cancelá-la.
//
// **Este ecrã já foi o dobro disto, e o que lhe saiu foi de propósito.** Era
// aqui que se escolhia o número de pessoas, se atribuíam os artigos um a um e
// se via a previsão antes de repartir — e era esse desvio que o dono descreveu
// como confuso, com o POS do Vendus à frente: lá, escolhe-se o número de
// pessoas encostado aos botões e o toque seguinte já está a cobrar a primeira
// pessoa. Passou a ser assim: o `PosFinalizar` tem o stepper e o `Dividir
// Conta`, e o `PosVenda` tem o `Separar Conta` (toca-se nos produtos desta
// pessoa, na própria conta). A previsão que aqui se fazia mudou-se para
// `lib/pos.js` — é a mesma conta, lida agora pelos dois ecrãs que a mostram.
//
// O que ficou é o que não tinha outro lugar: a lista de quem já pagou e de
// quem falta. **Não é uma paragem no caminho** — cobrada uma pessoa, o ecrã
// vai sozinho para a seguinte — é para onde se volta quando já não falta
// ninguém, e é o que o F5 e a tela de descanso recuperam (as partes vêm do
// servidor, `GET /pos/venda/repartidas`).
//
// **A decisão que manda aqui é a mesma que manda no servidor: cada parte é uma
// venda normal.** Este ecrã não emite nada, não cancela nada e não soma nenhum
// total de fatura: entrega cada parte aos caminhos que já existem — o
// `PosFinalizar` para a cobrar, o `cancelarVenda` para a deitar fora.

const eurosDeCentimos = (c) => euros((Number(c) || 0) / 100);


// --- A conta de uma pessoa (o painel da direita) ------------------------------

// A coluna "Fatia" é a que o POS do Vendus tem à esquerda do artigo (o `1`, o
// `0.5`), e diz o que ESTA pessoa leva daquela linha. No dividir é uma fracção
// (`1/3`), no separar são unidades inteiras (`1`, `2 de 3`).
//
// **No dividir não é a quantidade que vai na fatura, e é de propósito.** O
// servidor deriva do valor uma quantidade com cinco casas (0.3337 para um terço
// de 8,99 €) porque é essa que faz o Vendus facturar o cêntimo certo — um
// número que não diz nada a ninguém ao balcão. O que a operadora precisa de
// ler é quanto é que esta pessoa paga, e esse valor, ao lado, é exacto.
function ContaDaPessoa({ titulo, subtitulo, itens, totalCentimos, aviso }) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="shrink-0 border-b px-4 py-3">
        <p className="font-heading font-bold text-lg leading-tight">{titulo}</p>
        {subtitulo && <p className="text-sm text-muted-foreground mt-0.5">{subtitulo}</p>}
      </div>

      <div className="shrink-0 grid grid-cols-[1fr_4rem_6rem] gap-2 px-4 h-10 items-center border-b text-xs uppercase tracking-wide text-muted-foreground">
        <span>Produto</span>
        <span className="text-center">Fatia</span>
        <span className="text-right">Preço</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {itens.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6 gap-2 py-10">
            <Receipt className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-muted-foreground">Esta pessoa ainda não leva nada.</p>
          </div>
        ) : (
          itens.map((item, i) => {
            const { servico, escolhas } = resumoDoPedido(item.linha);
            return (
              <div
                key={`${item.linha.id}-${i}`}
                className="grid grid-cols-[1fr_4rem_6rem] gap-2 items-start px-4 py-3 border-b"
              >
                <div className="min-w-0">
                  <p className="font-medium leading-tight">{item.linha.produto_nome}</p>
                  {servico && <p className="text-xs text-muted-foreground leading-snug mt-0.5">{servico}</p>}
                  {escolhas && <p className="text-xs text-muted-foreground leading-snug mt-0.5">{escolhas}</p>}
                </div>
                <span className="font-heading font-bold text-base tabular-nums text-center">{item.fatia}</span>
                <span className="font-heading font-bold text-lg tabular-nums text-right">
                  {eurosDeCentimos(item.totalCentimos)}
                </span>
              </div>
            );
          })
        )}
      </div>

      {aviso}

      <div className="shrink-0 bg-primary text-primary-foreground px-4 py-3 flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold uppercase tracking-wide">Esta pessoa paga</span>
        <span className="font-heading font-bold text-4xl tabular-nums">{eurosDeCentimos(totalCentimos)}</span>
      </div>
    </div>
  );
}

// --- A tira das pessoas -------------------------------------------------------

// Uma pastilha por pessoa, com o que ela paga escrito nela — é aqui que se lê,
// de uma vez, o "3,00 / 3,00 / 2,99" de uma conta de 8,99 € por três. Depois da
// repartição feita, a mesma tira passa a mostrar o ESTADO de cada parte (paga,
// cancelada, por cobrar), porque é a mesma pergunta noutro momento: quem já
// está resolvido e quem falta.
function TiraDePessoas({ pessoas, escolhida, onEscolher }) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {pessoas.map((p, i) => (
        <button
          key={p.chave || i}
          type="button"
          onClick={() => onEscolher(i)}
          aria-pressed={i === escolhida}
          className={`shrink-0 rounded-xl border px-3 py-2 text-left min-w-[7.5rem] transition-colors ${
            i === escolhida ? 'bg-primary text-primary-foreground border-primary' : 'bg-card hover:bg-accent'
          }`}
        >
          <span className="block text-xs uppercase tracking-wide opacity-80">Pessoa {i + 1}</span>
          <span className="block font-heading font-bold text-lg tabular-nums">
            {eurosDeCentimos(p.totalCentimos)}
          </span>
          {p.estado && <span className="block text-xs mt-0.5 truncate">{p.estado}</span>}
        </button>
      ))}
    </div>
  );
}

// --- O cartão da divisão ------------------------------------------------------
//
// O cartão do POS do Vendus, e as quatro coisas que ele diz:
//
//   Divisão de Conta · 1/3 Pessoas · Falta Receber: 5,99 €
//   3,00 € / Pessoa · Total: 8,99 €
//
// `1/3 Pessoas` são as que JÁ pagaram (a parte delas foi emitida), e o
// `Falta Receber` é a soma das partes que ainda estão por cobrar — desce a
// cada fatura emitida, que é o único sinal de progresso que a operadora tem
// com três pessoas a pagar à vez. Uma parte CANCELADA não entra em nenhum dos
// dois e por isso é dita à parte: não foi recebida nem vai ser, e calá-la era
// deixar a conta a "faltar" um dinheiro que ninguém está à espera.
function CartaoDivisao({
  modo, cobradas, totalPessoas, faltaCentimos, canceladoCentimos, totalCentimos, porPessoa,
}) {
  return (
    <section className="rounded-2xl border-2 border-primary bg-primary/5 p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground flex items-center gap-1.5">
          {modo === 'dividir' ? <Divide className="h-4 w-4" /> : <Scissors className="h-4 w-4" />}
          {modo === 'dividir' ? 'Divisão de Conta' : 'Conta Separada'}
        </p>
        <p className="text-sm font-medium tabular-nums flex items-center gap-1.5">
          <Users className="h-4 w-4 text-muted-foreground" />
          {cobradas}/{totalPessoas} Pessoas
        </p>
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Falta receber</p>
          <p className="font-heading font-bold text-4xl md:text-5xl tabular-nums leading-tight">
            {eurosDeCentimos(faltaCentimos)}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="font-heading font-bold text-xl tabular-nums">{porPessoa}</p>
          <p className="text-sm text-muted-foreground tabular-nums">
            Total: {eurosDeCentimos(totalCentimos)}
          </p>
        </div>
      </div>

      {canceladoCentimos > 0 && (
        <p className="mt-3 text-sm text-muted-foreground flex items-start gap-1.5">
          <Ban className="h-4 w-4 shrink-0 mt-0.5" />
          <span>
            {eurosDeCentimos(canceladoCentimos)} em partes canceladas — esse dinheiro não entra na
            gaveta e não sai fatura nenhuma dele.
          </span>
        </p>
      )}
    </section>
  );
}

// --- O ecrã -------------------------------------------------------------------

export default function PosReparticao({
  modo = 'dividir',
  // As partes tal como o servidor as devolveu. Já não há o caso de elas ainda
  // não existirem: quem chega aqui chega DEPOIS de a conta estar repartida.
  partes = [],
  aCancelarParte = null,
  onVoltar,
  onCobrarParte,
  onCancelarParte,
  onTerminar,
}) {
  const [escolhida, setEscolhida] = useState(0);
  const [aConfirmarCancelar, setAConfirmarCancelar] = useState(null);

  const totais = partes.map((p) => centimos(p?.totais?.total));
  const cobradas = partes.filter((p) => p?.estado === 'emitida').length;
  const faltaCentimos = partes.reduce(
    (soma, p, i) => (p?.estado === 'aberta' ? soma + totais[i] : soma), 0,
  );
  const canceladoCentimos = partes.reduce(
    (soma, p, i) => (p?.estado === 'cancelada' ? soma + totais[i] : soma), 0,
  );

  const totalPessoas = partes.length;
  const visivel = Math.max(0, Math.min(escolhida, totalPessoas - 1));

  // O estado de cada parte em três palavras, para caber na pastilha. É o
  // `estado` que o SERVIDOR gravou, nunca uma memória deste ecrã: uma parte
  // que foi emitida noutro sítio, ou cancelada, tem de se ler aqui como o que
  // ela é agora.
  const estadoDaParte = (parte) => {
    if (!parte) return null;
    if (parte.estado === 'emitida') return parte.documento?.numero || 'Fatura emitida';
    if (parte.estado === 'cancelada') return 'Cancelada';
    return 'Por cobrar';
  };

  const pastilhas = partes.map((p, i) => ({
    chave: p?.id || i,
    totalCentimos: centimos(p?.totais?.total),
    estado: estadoDaParte(p),
  }));

  const parteVisivel = partes[visivel] || null;
  const contaVisivel = {
    titulo: `Pessoa ${visivel + 1} de ${totalPessoas}`,
    subtitulo: estadoDaParte(parteVisivel),
    itens: (parteVisivel?.linhas || []).map((linha) => ({
      linha,
      fatia: `${linha.quantidade}`,
      totalCentimos: centimos(contasDaLinha(linha).total),
    })),
    totalCentimos: centimos(parteVisivel?.totais?.total),
  };

  // O que se escreve na linha "X € / Pessoa" do cartão. Com as partes todas
  // iguais é um número só; com um cêntimo de diferença entre elas (a divisão
  // de 8,99 € por três dá 3,00 / 3,00 / 2,99) são os dois extremos, porque
  // escolher um dos dois e chamar-lhe "por pessoa" era prometer a uma delas um
  // valor que a fatura vai desmentir. No separar não há "por pessoa" nenhum
  // que se possa escrever: cada uma leva o que consumiu.
  const minimo = totais.length ? Math.min(...totais) : 0;
  const maximo = totais.length ? Math.max(...totais) : 0;
  const porPessoa = modo === 'separar'
    ? `${totalPessoas} partes`
    : (minimo === maximo
      ? `${eurosDeCentimos(minimo)} / Pessoa`
      : `${eurosDeCentimos(minimo)} a ${eurosDeCentimos(maximo)} / Pessoa`);

  const tudoResolvido = partes.length > 0 && partes.every((p) => p?.estado !== 'aberta');

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <header className="shrink-0 flex items-center gap-2 border-b bg-card px-3 h-16">
        <Button
          variant="ghost"
          size="icon"
          className="h-12 w-12"
          onClick={onVoltar}
          aria-label="Voltar ao balcão"
        >
          <ArrowLeft className="h-6 w-6" />
        </Button>
        <h2 className="font-heading font-bold text-xl">Cobrar as partes</h2>
      </header>

      <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
        <section className="flex-1 min-w-0 min-h-0 overflow-y-auto p-4 sm:p-6 space-y-4">
          <CartaoDivisao
            modo={modo}
            cobradas={cobradas}
            totalPessoas={totalPessoas}
            faltaCentimos={faltaCentimos}
            canceladoCentimos={canceladoCentimos}
            totalCentimos={totais.reduce((s, t) => s + t, 0)}
            porPessoa={porPessoa}
          />

          <TiraDePessoas pessoas={pastilhas} escolhida={visivel} onEscolher={setEscolhida} />

          {/* Cada parte com o que se pode fazer com ela. Emite-se parte a
              parte — e uma parte que não é paga CANCELA-SE, que é a única
              saída honesta para artigos que ninguém pagou. */}
          <section className="rounded-2xl border bg-card divide-y">
            {partes.map((parte, i) => {
              const aberta = parte?.estado === 'aberta';
              const emitida = parte?.estado === 'emitida';
              return (
                <div key={parte?.id || i} className="p-4 flex flex-wrap items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium flex items-center gap-1.5">
                      {emitida && <CheckCircle2 className="h-4 w-4 text-success shrink-0" />}
                      {parte?.estado === 'cancelada' && <Ban className="h-4 w-4 text-muted-foreground shrink-0" />}
                      Pessoa {i + 1}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {emitida
                        ? `Fatura ${parte.documento?.numero || 'emitida'}`
                        : parte?.estado === 'cancelada'
                          ? 'Cancelada — sem fatura e sem dinheiro'
                          : 'Por cobrar'}
                    </p>
                  </div>
                  <span className="font-heading font-bold text-2xl tabular-nums shrink-0">
                    {eurosDeCentimos(centimos(parte?.totais?.total))}
                  </span>
                  {aberta && (
                    <div className="flex gap-2 shrink-0">
                      <Button
                        type="button"
                        variant="outline"
                        className="h-12"
                        onClick={() => setAConfirmarCancelar({ parte, numero: i + 1 })}
                        disabled={!!aCancelarParte}
                        aria-label={`Cancelar a parte da pessoa ${i + 1}`}
                        title={`Cancelar a parte da pessoa ${i + 1} — sai sem fatura e sem dinheiro`}
                      >
                        {aCancelarParte === parte.id
                          ? <Loader2 className="h-5 w-5 animate-spin" />
                          : <Trash2 className="h-5 w-5" />}
                      </Button>
                      <Button type="button" className="h-12" onClick={() => onCobrarParte(parte)}>
                        <Coins className="h-5 w-5 mr-2" />
                        Cobrar
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        </section>

        <aside className="w-full lg:w-[23rem] xl:w-[26rem] shrink-0 min-h-0 border-t lg:border-t-0 lg:border-l bg-card flex flex-col">
          <ContaDaPessoa
            titulo={contaVisivel.titulo}
            subtitulo={contaVisivel.subtitulo}
            itens={contaVisivel.itens}
            totalCentimos={contaVisivel.totalCentimos}
            aviso={parteVisivel && parteVisivel.estado === 'cancelada' ? (
              <div className="shrink-0 border-t bg-muted/60 px-4 py-3 text-sm text-muted-foreground flex items-start gap-2">
                <Ban className="h-4 w-4 shrink-0 mt-0.5" />
                <span>
                  Esta parte foi cancelada: estes artigos saíram sem fatura e sem dinheiro.
                </span>
              </div>
            ) : null}
          />
        </aside>
      </div>

      <div className="shrink-0 border-t bg-card p-4">
        <div className="mx-auto w-full max-w-3xl">
          {!tudoResolvido && (
            <p className="text-sm text-muted-foreground mb-3">
              Cobre uma parte de cada vez. Uma parte que não é paga cancela-se — os artigos
              dela saem sem fatura e sem dinheiro.
            </p>
          )}
          <Button
            className="w-full h-16 text-lg font-heading font-bold"
            variant={tudoResolvido ? 'default' : 'outline'}
            onClick={tudoResolvido ? onTerminar : onVoltar}
          >
            {tudoResolvido ? 'Nova Venda' : 'Voltar ao balcão'}
          </Button>
        </div>
      </div>

      <AlertDialog
        open={!!aConfirmarCancelar}
        onOpenChange={(aberto) => { if (!aberto) setAConfirmarCancelar(null); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Cancelar a parte da pessoa {aConfirmarCancelar?.numero}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Os artigos desta parte saem sem fatura e sem dinheiro:{' '}
              {eurosDeCentimos(centimos(aConfirmarCancelar?.parte?.totais?.total))} que não entram
              na gaveta e não são declarados. As outras partes continuam como estão.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="h-12">Manter a parte</AlertDialogCancel>
            <AlertDialogAction
              className="h-12 bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                const alvo = aConfirmarCancelar?.parte;
                setAConfirmarCancelar(null);
                if (alvo) onCancelarParte(alvo);
              }}
            >
              Cancelar a parte
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
