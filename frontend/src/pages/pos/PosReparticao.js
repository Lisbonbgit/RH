import React, { useMemo, useState } from 'react';
import {
  AlertTriangle, ArrowLeft, Ban, CheckCircle2, Coins, Divide, Loader2, Minus, Plus,
  Receipt, Scissors, Trash2, Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle,
  AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { resumoDoPedido } from './PosPedidoGuiado';
import { contasDaLinha, repartirCentimos } from '@/lib/pos';

// Dividir e separar a conta (Plano 2D, Task 5): três amigos, dois açaís e uma
// Coca-Cola — ou dividem por igual, ou cada um paga o que consumiu, e cada um
// leva a SUA fatura.
//
// **A decisão que manda neste ficheiro é a mesma que manda no servidor: cada
// parte é uma venda normal.** Este ecrã não emite nada, não cancela nada e não
// soma nenhum total de fatura: constrói o pedido de repartição, mostra o que
// vai acontecer ANTES de acontecer, e daí em diante entrega cada parte aos
// caminhos que já existem — o `PosFinalizar` para a cobrar, o `cancelarVenda`
// para a deitar fora. Nada em `precos.linha_de_venda`, `fiscal.py` ou
// `caixa_math` sabe sequer que este ecrã existe.
//
// **Os números que contam são os do servidor.** As contas que aqui se fazem
// servem para uma coisa só: dizer à operadora, com o cliente à frente, quanto
// vai pagar cada pessoa antes de ela carregar no botão. Assim que a repartição
// é feita, o ecrã deita fora a sua própria previsão e passa a mostrar as
// partes tal como o servidor as devolveu — e é por isso que a previsão tem de
// ser a MESMA conta que ele faz: um ecrã a prometer 3,00 / 3,00 / 2,99 e um
// servidor a repartir de outra maneira é uma promessa que a fatura desmente à
// frente do cliente.

const euros = (valor) =>
  `€ ${(Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// O dinheiro conta-se em CÊNTIMOS INTEIROS, do princípio ao fim. É a mesma
// razão do cabeçalho de `reparticao.py`: `round()` sobre a representação
// binária come cêntimos sem avisar, e numa conta repartida isso é a soma das
// faturas a divergir do que entrou na gaveta.
const centimos = (valor) => Math.round((Number(valor) || 0) * 100);
const eurosDeCentimos = (c) => euros((Number(c) || 0) / 100);

// A MESMA repartição proporcional do servidor (`venda.py::_reparte_por_peso`),
// para os descontos: chão da divisão inteira para cada peso, e os cêntimos que
// sobram vão, um a um, para quem tem o maior resto por arredondar. Tudo em
// aritmética inteira — nunca uma divisão em vírgula flutuante.
//
// O desempate por índice ascendente está escrito à mão (`|| a - b`) e não
// deixado ao acaso do motor: o `sorted` do Python é estável e mantém a ordem
// dos índices em restos iguais; um `sort` que os trocasse punha o cêntimo numa
// pessoa diferente da que o servidor vai escolher.
const repartirPorPeso = (totalCentimos, pesos) => {
  const n = pesos.length;
  const somaPesos = pesos.reduce((soma, p) => soma + p, 0);
  if (somaPesos <= 0 || totalCentimos === 0) return new Array(n).fill(0);
  const numeradores = pesos.map((peso) => totalCentimos * peso);
  const base = numeradores.map((num) => Math.floor(num / somaPesos));
  const restos = numeradores.map((num) => num % somaPesos);
  const falta = totalCentimos - base.reduce((soma, b) => soma + b, 0);
  const ordem = base.map((_, i) => i).sort((a, b) => restos[b] - restos[a] || a - b);
  ordem.slice(0, falta).forEach((i) => { base[i] += 1; });
  return base;
};

// --- A previsão do DIVIDIR ---------------------------------------------------

// A mesma repartição que o servidor faz a uma linha (`venda.py::
// _partes_de_uma_linha`): reparte-se o BRUTO por N e o DESCONTO por N, em
// cêntimos, e a fatia de cada pessoa é a diferença entre os dois. Nunca se
// reparte o total da linha de uma vez — o `round` de cada fatia não devolve o
// que devolve aplicado ao todo, e é essa diferença que faz a soma das partes
// divergir da conta.
//
// Devolve uma entrada por pessoa, e `null` na pessoa que não leva nada desta
// linha — os dois casos em que isso acontece são os do servidor, e por isso
// estão aqui: a linha que não vale nada (um artigo oferecido, a preço 0) vai
// INTEIRA para a primeira parte, e a fatia que não chega a um cêntimo (uma
// linha de 2 cêntimos por três) não entra na conta dessa pessoa.
const fatiasDaLinha = (linha, partes) => {
  const { bruto, desconto } = contasDaLinha(linha);
  const brutoCentimos = centimos(bruto);
  if (brutoCentimos === 0) {
    return Array.from({ length: partes }, (_, i) => (
      i === 0 ? { fatia: 'inteiro', totalCentimos: 0 } : null
    ));
  }
  const brutos = repartirCentimos(brutoCentimos, partes);
  const descontos = repartirCentimos(centimos(desconto), partes);
  return brutos.map((b, i) => (
    b === 0 ? null : { fatia: `1/${partes}`, totalCentimos: b - descontos[i] }
  ));
};

// A conta de cada pessoa se a divisão for por N — a previsão inteira, com o
// desconto global da mãe repartido em fatias iguais, tal como
// `venda.py::dividir_conta` faz.
const previsaoDoDividir = (mae, partes) => {
  const linhas = mae?.linhas || [];
  const porLinha = linhas.map((linha) => fatiasDaLinha(linha, partes));
  const globais = repartirCentimos(centimos(mae?.totais?.desconto_global), partes);
  return Array.from({ length: partes }, (_, i) => {
    const daPessoa = linhas
      .map((linha, l) => (porLinha[l][i] ? { linha, ...porLinha[l][i] } : null))
      .filter(Boolean);
    const soma = daPessoa.reduce((total, item) => total + item.totalCentimos, 0);
    return { linhas: daPessoa, totalCentimos: soma - globais[i] };
  });
};

// --- A previsão do SEPARAR ---------------------------------------------------

// Quantas unidades desta linha estão atribuídas a esta pessoa. A atribuição é
// um dicionário por pessoa (`{ [linha_id]: unidades }`) e não uma lista de
// linhas: ao balcão toca-se muitas vezes no mesmo artigo, e somar unidades a
// uma chave é o que faz o toque repetido ser o gesto natural.
const atribuidas = (mapa, linhaId) => Number(mapa?.[linhaId]) || 0;

// A conta de cada pessoa com as linhas que o staff lhe atribuiu — a mesma
// ordem de contas do `venda.py::separar_conta`:
//   1. o bruto de cada fatia é `unitário × unidades atribuídas`;
//   2. o desconto DA LINHA reparte-se PROPORCIONALMENTE às unidades de cada
//      pessoa (nunca copiado inteiro: um "-3,00 €" copiado para as três partes
//      descontava 9,00 € numa conta que descontou 3,00);
//   3. o desconto GLOBAL reparte-se proporcionalmente ao LÍQUIDO de cada parte
//      — que é a mesma base sobre a qual ele incide na mãe.
const previsaoDoSeparar = (mae, atribuicao) => {
  const linhas = mae?.linhas || [];
  const porPessoa = atribuicao.map(() => []);

  linhas.forEach((linha) => {
    const { unitario, desconto } = contasDaLinha(linha);
    const unidades = atribuicao.map((mapa) => atribuidas(mapa, linha.id));
    const brutos = unidades.map((n) => centimos(unitario * n));
    const descontos = repartirPorPeso(centimos(desconto), unidades);
    unidades.forEach((n, i) => {
      if (n <= 0) return;
      porPessoa[i].push({
        linha,
        fatia: n === (Number(linha.quantidade) || 0) ? `${n}` : `${n} de ${linha.quantidade}`,
        totalCentimos: brutos[i] - descontos[i],
      });
    });
  });

  const liquidos = porPessoa.map((itens) => itens.reduce((soma, i) => soma + i.totalCentimos, 0));
  const globais = repartirPorPeso(centimos(mae?.totais?.desconto_global), liquidos);
  return porPessoa.map((itens, i) => ({
    linhas: itens,
    totalCentimos: liquidos[i] - globais[i],
  }));
};

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
  mae,
  modo = 'dividir',
  onModo,
  // As partes JÁ criadas (vendas normais, tal como o servidor as devolveu), ou
  // `null` enquanto a repartição ainda não foi feita. Vive no PosVenda e não
  // aqui: este ecrã desmonta-se de cada vez que se vai cobrar uma parte, e o
  // que se perdia com ele era exactamente a lista do que falta receber.
  partes = null,
  aRepartir = false,
  aCancelarParte = null,
  onVoltar,
  onRepartir,
  onCobrarParte,
  onCancelarParte,
  onTerminar,
}) {
  const linhasDaMae = useMemo(() => mae?.linhas || [], [mae]);
  const totalDaMaeCentimos = centimos(mae?.totais?.total);

  const [pessoas, setPessoas] = useState(2);
  // Uma entrada por pessoa: `{ [linha_id]: unidades }`. Começa com duas —
  // separar por uma é não separar, e o servidor recusa (`PedidoSeparar`).
  const [atribuicao, setAtribuicao] = useState([{}, {}]);
  const [escolhida, setEscolhida] = useState(0);
  const [aConfirmarCancelar, setAConfirmarCancelar] = useState(null);

  // Uma linha com quantidade fraccionada não se separa por artigo: o servidor
  // recusa com 422 uma quantidade que não seja um número inteiro de unidades
  // (`PedidoSepararLinha`), e é assim de propósito — atribui-se meio açaí a
  // ninguém. Acontece numa conta que já É uma parte de outra divisão (as
  // quantidades dela têm cinco casas). Dizê-lo aqui é melhor do que deixá-la
  // montar a atribuição toda para levar com o 422 no fim.
  const comFraccao = useMemo(
    () => linhasDaMae.filter((li) => !Number.isInteger(Number(li.quantidade))),
    [linhasDaMae],
  );

  // --- Antes de repartir: a previsão -----------------------------------------

  const previsao = useMemo(() => {
    if (partes) return null;
    if (!mae) return [];
    return modo === 'dividir'
      ? previsaoDoDividir(mae, pessoas)
      : previsaoDoSeparar(mae, atribuicao);
  }, [partes, mae, modo, pessoas, atribuicao]);

  // Quantas unidades de cada linha já foram atribuídas a alguém, e quantas
  // faltam. É a conta central do separar: o servidor recusa (com 422) uma
  // separação que deixe artigos por atribuir, e é melhor a operadora ver isso
  // antes de carregar do que depois.
  const porAtribuir = useMemo(() => {
    const mapa = {};
    linhasDaMae.forEach((linha) => {
      const dadas = atribuicao.reduce((soma, m) => soma + atribuidas(m, linha.id), 0);
      mapa[linha.id] = (Number(linha.quantidade) || 0) - dadas;
    });
    return mapa;
  }, [linhasDaMae, atribuicao]);

  const faltamUnidades = Object.values(porAtribuir).reduce(
    (soma, quantas) => soma + Math.max(0, quantas), 0,
  );

  // --- Depois de repartir: o que falta receber --------------------------------

  const emCobranca = useMemo(() => {
    if (!partes) return null;
    const totais = partes.map((p) => centimos(p?.totais?.total));
    return {
      totais,
      cobradas: partes.filter((p) => p?.estado === 'emitida').length,
      faltaCentimos: partes.reduce(
        (soma, p, i) => (p?.estado === 'aberta' ? soma + totais[i] : soma), 0,
      ),
      canceladoCentimos: partes.reduce(
        (soma, p, i) => (p?.estado === 'cancelada' ? soma + totais[i] : soma), 0,
      ),
    };
  }, [partes]);

  if (!mae && !partes) return null;

  const totalPessoas = partes ? partes.length : (previsao || []).length;
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

  const pastilhas = partes
    ? partes.map((p, i) => ({
      chave: p?.id || i,
      totalCentimos: centimos(p?.totais?.total),
      estado: estadoDaParte(p),
    }))
    : (previsao || []).map((p, i) => ({ chave: i, totalCentimos: p.totalCentimos }));

  const contaVisivel = partes
    ? {
      titulo: `Pessoa ${visivel + 1} de ${totalPessoas}`,
      subtitulo: estadoDaParte(partes[visivel]),
      itens: (partes[visivel]?.linhas || []).map((linha) => ({
        linha,
        fatia: `${linha.quantidade}`,
        totalCentimos: centimos(contasDaLinha(linha).total),
      })),
      totalCentimos: centimos(partes[visivel]?.totais?.total),
    }
    : {
      titulo: `Pessoa ${visivel + 1} de ${totalPessoas}`,
      subtitulo: modo === 'dividir'
        ? 'Leva a mesma fatia de cada artigo da conta.'
        : 'Leva os artigos que lhe forem atribuídos.',
      itens: (previsao || [])[visivel]?.linhas || [],
      totalCentimos: (previsao || [])[visivel]?.totalCentimos || 0,
    };

  // O que se escreve na linha "X € / Pessoa" do cartão. Com as partes todas
  // iguais é um número só; com um cêntimo de diferença entre elas (a divisão
  // de 8,99 € por três dá 3,00 / 3,00 / 2,99) são os dois extremos, porque
  // escolher um dos dois e chamar-lhe "por pessoa" era prometer a uma delas um
  // valor que a fatura vai desmentir. No separar não há "por pessoa" nenhum
  // que se possa escrever: cada uma leva o que consumiu.
  const totaisDasPartes = partes ? emCobranca.totais : (previsao || []).map((p) => p.totalCentimos);
  const minimo = totaisDasPartes.length ? Math.min(...totaisDasPartes) : 0;
  const maximo = totaisDasPartes.length ? Math.max(...totaisDasPartes) : 0;
  const porPessoa = modo === 'separar'
    ? `${totalPessoas} partes`
    : (minimo === maximo
      ? `${eurosDeCentimos(minimo)} / Pessoa`
      : `${eurosDeCentimos(minimo)} a ${eurosDeCentimos(maximo)} / Pessoa`);

  // --- O que impede de repartir ----------------------------------------------
  //
  // A ÚNICA verdade sobre "porque é que o botão está cinzento", pelo mesmo
  // desenho do `motivoBloqueio` do PosFinalizar: nada aqui pode desligar o
  // botão sem produzir, no mesmo sítio, a frase que explica porquê. Os limites
  // são os do servidor (`venda.py::separar_conta` e os modelos do pedido),
  // para o ecrã não deixar passar o que ele recusa nem recusar o que ele
  // aceitaria.
  const motivoBloqueio = (() => {
    if (linhasDaMae.length === 0) {
      return 'Esta conta ainda não tem nada — não há o que repartir.';
    }
    if (totalDaMaeCentimos <= 0) {
      return 'O total da conta tem de ser positivo para se repartir — reveja o desconto aplicado.';
    }
    if (modo === 'dividir') {
      const aZero = (previsao || []).findIndex((p) => p.totalCentimos <= 0);
      if (aZero >= 0) {
        // Uma parte a 0,00 € nasce presa: `fiscal.finalizar` recusa um total
        // que não seja positivo, e a única saída passa a ser cancelá-la. É
        // preferível dizê-lo com o número de pessoas ainda por escolher do que
        // deixar nascer uma venda que nunca fecha.
        return `Com ${pessoas} pessoas, a pessoa ${aZero + 1} fica a ${eurosDeCentimos(0)} — e uma parte a zero não se consegue emitir. Escolha outro número de pessoas.`;
      }
      return null;
    }
    if (comFraccao.length > 0) {
      return `Esta conta tem artigos com quantidade fraccionada (${comFraccao[0].produto_nome}), e ao separar atribuem-se artigos inteiros. Use o Dividir Conta.`;
    }
    if (faltamUnidades > 0) {
      // A frase nomeia o artigo em falta: "faltam 2 artigos" mandava-a
      // procurar quais, e o que ela precisa é do nome que está na conta.
      const primeira = linhasDaMae.find((li) => porAtribuir[li.id] > 0);
      return `Ainda há artigos por atribuir a alguém — ${primeira?.produto_nome} (${porAtribuir[primeira.id]}). Um artigo que não é de ninguém sai da loja sem fatura e sem pagamento.`;
    }
    const vazia = (previsao || []).findIndex((p) => p.linhas.length === 0);
    if (vazia >= 0) {
      return `A pessoa ${vazia + 1} não leva nada. Atribua-lhe alguma coisa, ou retire-a da lista.`;
    }
    const semValor = (previsao || []).findIndex((p) => p.totalCentimos <= 0);
    if (semValor >= 0) {
      return `A pessoa ${semValor + 1} fica a ${eurosDeCentimos(0)} — uma parte a zero não se consegue emitir. Reveja a atribuição.`;
    }
    return null;
  })();

  const repartir = () => {
    if (motivoBloqueio || aRepartir) return;
    if (modo === 'dividir') { onRepartir({ modo, partes: pessoas }); return; }
    onRepartir({
      modo,
      partes: atribuicao.map((mapa) => ({
        linhas: linhasDaMae
          .filter((li) => atribuidas(mapa, li.id) > 0)
          .map((li) => ({ linha_id: li.id, quantidade: atribuidas(mapa, li.id) })),
      })),
    });
  };

  const mudarAtribuicao = (linhaId, delta) => {
    setAtribuicao((lista) => lista.map((mapa, i) => {
      if (i !== visivel) return mapa;
      const nova = Math.max(0, atribuidas(mapa, linhaId) + delta);
      const copia = { ...mapa };
      if (nova === 0) delete copia[linhaId];
      else copia[linhaId] = nova;
      return copia;
    }));
  };

  const acrescentarPessoa = () => {
    if (modo === 'dividir') { setPessoas((n) => Math.min(20, n + 1)); return; }
    if (atribuicao.length >= 20) return;
    setAtribuicao((lista) => [...lista, {}]);
    // A pessoa nova passa a ser a escolhida — é nela que a operadora vai tocar
    // a seguir, e obrigá-la a ir buscá-la à tira era um toque a mais com o
    // cliente à frente.
    setEscolhida(atribuicao.length);
  };

  // Retira-se sempre a ÚLTIMA pessoa, e só se ela não levar nada. Retirar uma
  // do meio da lista devolvia os artigos dela a lado nenhum — desapareciam da
  // atribuição sem voltarem a aparecer como "por atribuir" em sítio nenhum que
  // ela visse, e a separação seguia com artigos a menos. Com artigos atribuídos
  // o botão fica desligado, e a saída é retirá-los primeiro (o `−` de cada
  // linha), que é o gesto que os devolve à lista do que falta.
  const podeRetirarPessoa = totalPessoas > 2 && (
    modo === 'dividir' || Object.keys(atribuicao[atribuicao.length - 1] || {}).length === 0
  );

  const retirarPessoa = () => {
    if (!podeRetirarPessoa) return;
    if (modo === 'dividir') { setPessoas((n) => Math.max(2, n - 1)); return; }
    setAtribuicao((lista) => lista.slice(0, -1));
  };

  const parteVisivel = partes ? partes[visivel] : null;
  const tudoResolvido = !!partes && partes.every((p) => p?.estado !== 'aberta');

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <header className="shrink-0 flex items-center gap-2 border-b bg-card px-3 h-16">
        <Button
          variant="ghost"
          size="icon"
          className="h-12 w-12"
          onClick={onVoltar}
          disabled={aRepartir}
          aria-label={partes ? 'Voltar ao balcão' : 'Voltar ao finalizar'}
        >
          <ArrowLeft className="h-6 w-6" />
        </Button>
        <h2 className="font-heading font-bold text-xl">
          {partes ? 'Cobrar as partes' : (modo === 'dividir' ? 'Dividir Conta' : 'Separar Conta')}
        </h2>
      </header>

      <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
        <section className="flex-1 min-w-0 min-h-0 overflow-y-auto p-4 sm:p-6 space-y-4">
          {/* Os dois modos, exclusivos — e só enquanto a repartição não estiver
              feita: depois de as partes existirem não há modo nenhum para
              trocar, e um botão que não faz nada é pior do que não existir.
              Uma conta divide-se de UMA maneira: ou por igual, ou pelo que
              cada um consumiu. */}
          {!partes && (
            <div className="grid grid-cols-2 gap-2.5">
              {[
                { id: 'dividir', nome: 'Dividir Conta', icone: Divide, nota: 'Todos pagam o mesmo' },
                { id: 'separar', nome: 'Separar Conta', icone: Scissors, nota: 'Cada um paga o que consumiu' },
              ].map(({ id, nome, icone: Icone, nota }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => onModo(id)}
                  aria-pressed={modo === id}
                  disabled={aRepartir}
                  className={`rounded-xl border p-3 text-left transition-colors disabled:opacity-50 ${
                    modo === id ? 'bg-primary text-primary-foreground border-primary' : 'bg-card hover:bg-accent'
                  }`}
                >
                  <span className="font-medium flex items-center gap-1.5">
                    <Icone className="h-4 w-4 shrink-0" />
                    {nome}
                  </span>
                  <span className="block text-xs mt-1 opacity-80">{nota}</span>
                </button>
              ))}
            </div>
          )}

          <CartaoDivisao
            modo={modo}
            cobradas={emCobranca ? emCobranca.cobradas : 0}
            totalPessoas={totalPessoas}
            faltaCentimos={emCobranca ? emCobranca.faltaCentimos : totalDaMaeCentimos}
            canceladoCentimos={emCobranca ? emCobranca.canceladoCentimos : 0}
            totalCentimos={partes ? totaisDasPartes.reduce((s, t) => s + t, 0) : totalDaMaeCentimos}
            porPessoa={porPessoa}
          />

          <TiraDePessoas pessoas={pastilhas} escolhida={visivel} onEscolher={setEscolhida} />

          {/* Antes de repartir: o contador de pessoas (dividir) ou a atribuição
              artigo a artigo (separar). */}
          {!partes && (
            <section className="rounded-2xl border bg-card p-5 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-muted-foreground">Pessoas</p>
                  <p className="text-xs text-muted-foreground/80 mt-0.5">
                    {modo === 'dividir'
                      ? 'Entre 2 e 20 — a conta reparte-se em partes iguais ao cêntimo.'
                      : 'Toque nos artigos que são desta pessoa.'}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="h-14 w-14"
                    onClick={retirarPessoa}
                    disabled={aRepartir || !podeRetirarPessoa}
                    aria-label="Menos uma pessoa"
                    title={
                      totalPessoas > 2 && !podeRetirarPessoa
                        ? 'A última pessoa já leva artigos — retire-os primeiro.'
                        : undefined
                    }
                  >
                    <Minus className="h-6 w-6" />
                  </Button>
                  <span className="font-heading font-bold text-4xl tabular-nums w-14 text-center">
                    {totalPessoas}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="h-14 w-14"
                    onClick={acrescentarPessoa}
                    disabled={aRepartir || totalPessoas >= 20}
                    aria-label="Mais uma pessoa"
                  >
                    <Plus className="h-6 w-6" />
                  </Button>
                </div>
              </div>

              {modo === 'separar' && (
                <div className="rounded-xl border divide-y">
                  {linhasDaMae.map((linha) => {
                    const minhas = atribuidas(atribuicao[visivel], linha.id);
                    const faltam = porAtribuir[linha.id];
                    const { servico, escolhas } = resumoDoPedido(linha);
                    return (
                      <div key={linha.id} className="flex items-stretch">
                        <button
                          type="button"
                          onClick={() => mudarAtribuicao(linha.id, 1)}
                          disabled={aRepartir || faltam <= 0 || comFraccao.length > 0}
                          className="flex-1 min-w-0 text-left px-4 py-3 flex items-start gap-3 hover:bg-accent disabled:opacity-50 disabled:hover:bg-transparent"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block font-medium leading-tight">{linha.produto_nome}</span>
                            {servico && <span className="block text-xs text-muted-foreground leading-snug mt-0.5">{servico}</span>}
                            {escolhas && <span className="block text-xs text-muted-foreground leading-snug mt-0.5">{escolhas}</span>}
                            <span className={`block text-xs mt-0.5 tabular-nums ${faltam > 0 ? 'text-warning' : 'text-muted-foreground'}`}>
                              {faltam > 0
                                ? `${faltam} de ${linha.quantidade} por atribuir`
                                : `${linha.quantidade} de ${linha.quantidade} atribuídos`}
                            </span>
                          </span>
                          <span className="font-heading font-bold text-2xl tabular-nums shrink-0 w-10 text-right">
                            {minhas}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => mudarAtribuicao(linha.id, -1)}
                          disabled={aRepartir || minhas <= 0}
                          aria-label={`Retirar ${linha.produto_nome} desta pessoa`}
                          className="shrink-0 w-14 flex items-center justify-center border-l hover:bg-accent disabled:opacity-30 disabled:hover:bg-transparent"
                        >
                          <Minus className="h-5 w-5" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          )}

          {/* Depois de repartir: cada parte com o que se pode fazer com ela.
              Emite-se parte a parte — e uma parte que não é paga CANCELA-SE,
              que é a única saída honesta para artigos que ninguém pagou. */}
          {partes && (
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
          )}
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
          {!partes ? (
            <>
              {/* A razão vive encostada ao botão que ela está a tentar carregar
                  — vem do mesmo `motivoBloqueio` que o desliga, por isso não há
                  forma de acrescentar amanhã uma condição nova e voltar ao
                  silêncio. */}
              {motivoBloqueio && (
                <div className="mb-3 flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3">
                  <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
                  <p className="text-sm">
                    <span className="font-semibold">Para {modo === 'dividir' ? 'dividir' : 'separar'}: </span>
                    {motivoBloqueio}
                  </p>
                </div>
              )}
              <Button
                className="w-full h-16 text-lg font-heading font-bold"
                disabled={!!motivoBloqueio || aRepartir}
                onClick={repartir}
              >
                {aRepartir ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin mr-2" />
                    A repartir a conta…
                  </>
                ) : (
                  modo === 'dividir'
                    ? `DIVIDIR POR ${totalPessoas} PESSOAS`
                    : `SEPARAR EM ${totalPessoas} PARTES`
                )}
              </Button>
              {/* Dito ANTES, e não depois: a partir do momento em que a conta é
                  repartida a mãe deixa de aceitar seja o que for, e não há rota
                  nenhuma que desfaça uma divisão. */}
              <p className="text-xs text-muted-foreground mt-2 leading-snug">
                A conta passa a {totalPessoas} contas separadas, cada uma com a sua fatura. Depois
                disto a conta original deixa de aceitar produtos, alterações e descontos, e a
                divisão não se desfaz.
              </p>
            </>
          ) : (
            <>
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
            </>
          )}
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
