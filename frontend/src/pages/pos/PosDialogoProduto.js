import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ArrowLeft, Loader2, Minus, Plus, SlidersHorizontal, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import PosCampoValor from './PosCampoValor';
import PosPersonalizacoes, { errosDeSelecao, resumoDaSelecao } from './PosPersonalizacoes';
import { temMaisDe2CasasDecimaisPos } from '@/lib/pos';

// Os códigos são os do Vendus (`_TAXAS` em faturacao/precos.py). A operadora vê
// a PERCENTAGEM — é o que ela sabe de cor do balcão — mas o que viaja para o
// servidor é sempre o CÓDIGO. E não há aqui nenhum IVA por omissão: o
// precos.py abre com a história da app que tinha `vat_rate = prod.get(
// 'vat_rate', 13)` e faturou refrigerantes a 13% em vez de 23% durante meses.
// Se o produto do catálogo não trouxer `tax_id`, este ecrã não grava (ver
// `razoes`) em vez de escolher um por ela.
const TAXAS_IVA = [
  { codigo: 'NOR', etiqueta: '23%' },
  { codigo: 'INT', etiqueta: '13%' },
  { codigo: 'RED', etiqueta: '6%' },
  { codigo: 'ISE', etiqueta: '0%' },
];

const euros = (valor) =>
  `€ ${(Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// Arredonda a 2 casas a CADA passo, como o servidor faz em
// `precos.linha_de_venda` e `venda.py::_totais` — não uma vez no fim. Uma
// única divergência conhecida: num desconto em % que caia exactamente a meio
// cêntimo, o Python arredonda para o par e o JavaScript para cima, e a
// estimativa pode ficar a um cêntimo do papel. É por isso que o número que
// manda depois de Gravar é sempre o `venda.totais` que o servidor devolve, e
// nunca este.
const cent = (valor) => Math.round(valor * 100) / 100;

// Um campo vazio é vazio, não é zero: `Number('')` dá 0, e era assim que um
// preço apagado a meio virava um artigo oferecido sem ninguém pedir.
const numeroOuNulo = (texto) => {
  if (texto === '' || texto === null || texto === undefined) return null;
  const numero = Number(texto);
  return Number.isFinite(numero) ? numero : null;
};

const textoDeNumero = (valor) => (valor === null || valor === undefined || valor === '' ? '' : String(valor));

// A mesma normalização do PosCampoValor (aceita a vírgula do teclado
// português, recusa uma segunda separação decimal), aqui só para a
// percentagem — que não é dinheiro e por isso não passa por esse campo. Todo
// o resto do dinheiro deste ecrã (preço unitário e desconto em €) é
// PosCampoValor, para não haver duas maneiras de escrever um valor no POS.
const aceitarNumero = (texto) => {
  const comPonto = String(texto).replace(',', '.');
  const limpo = comPonto.replace(/[^0-9.]/g, '');
  const partes = limpo.split('.');
  return partes.length > 2 ? `${partes[0]}.${partes.slice(1).join('')}` : limpo;
};

// O que o SERVIDOR já cobra por esta linha quando este ecrã não manda override
// nenhum — e que NÃO é o produto do catálogo. `venda.py::_produto_snapshot`
// monta o "produto" a partir do RETRATO gravado na própria linha
// (`produto_nome`/`produto_preco`/`produto_tax_id`, escritos uma única vez em
// `juntar_linha` e nunca mais tocados — o `PedidoEditarLinha` nem sequer os
// tem), e é esse retrato que vai para a Fatura Simplificada.
//
// O catálogo deste browser, esse, é carregado UMA VEZ por caixa e nunca mais
// (o useEffect de arranque do PosVenda só depende do id da caixa), por isso a
// meio da manhã pode já estar a mentir. Com o catálogo como referência, o
// defeito era duplo e saía no papel: o gestor corrige "Açaí Grande" de 8,99
// para 9,99 às 11:00, a linha picada às 11:05 é gravada e cobrada a 9,99, mas
// o campo "Preço Unitário" mostrava 8,99 (o cartão em cache) — e Gravar não
// repunha nada, porque 8,99 === 8,99 do catálogo dava `preco_override: null` e
// o servidor mantinha os 9,99. Não havia maneira NENHUMA de pôr 8,99. A versão
// do IVA era pior, porque é fiscal: linha gravada a INT (13%) com o catálogo em
// cache já em NOR, a lista mostrava "23%", a fatura saía a 13%, e escolher
// "23%" não produzia `tax_override` nenhum por ser igual ao catálogo velho.
//
// Daí a regra: a editar uma linha que JÁ ESTÁ na conta, a base é sempre o
// retrato dela; só numa linha NOVA é que o catálogo é a referência certa — é
// dele que o servidor vai tirar o retrato nesse instante. Sem inventar
// fallbacks para o catálogo quando o retrato vier vazio: forçar um override
// explícito é sempre melhor do que voltar a comparar com um valor que o
// servidor não usa.
const baseDaLinha = (produto, linha) =>
  linha
    ? { preco: numeroOuNulo(linha.produto_preco), taxa: linha.produto_tax_id || '' }
    : { preco: numeroOuNulo(produto?.preco), taxa: produto?.tax_id || '' };

// O estado do diálogo nasce SEMPRE da base fiscal acima + da linha (quando se
// está a editar). Uma função à parte porque é preciso repô-lo quando o pai
// troca de produto sem desmontar o componente — ver o useEffect adiante.
const valoresIniciais = (produto, linha, grupos, base) => {
  const opcoes = Array.isArray(linha?.opcoes) ? linha.opcoes : [];
  return {
    quantidade: String(linha?.quantidade ?? 1),
    // O número que se MOSTRA sai da mesma base contra a qual se decide o
    // override (ver `gravar`). São duas metades do mesmo defeito e é fácil
    // corrigir só uma: com a base certa aqui e o catálogo lá em baixo, o campo
    // passava a mostrar o preço verdadeiro e continuava impossível de repor.
    preco: textoDeNumero(linha?.preco_override ?? base.preco),
    // Pré-seleccionado com o IVA que esta linha leva HOJE: a lista mostra
    // sempre qual é, e só uma escolha DIFERENTE desta vira `tax_override`.
    taxa: linha?.tax_override || base.taxa,
    descontoPct: textoDeNumero(linha?.desconto_pct),
    descontoEur: textoDeNumero(linha?.desconto_eur),
    opcoes,
    // "Se tiver personalizações obrigatórias, abre logo o painel dos toppings"
    // (Plano 2C, Task 3). Só numa linha NOVA: a abrir uma linha que já está na
    // conta, a operadora quer quase sempre a quantidade ou o preço, e saltar-
    // -lhe o painel dos toppings à frente escondia-lhe o total que ela foi lá
    // ver.
    vista: linha == null && errosDeSelecao(grupos || [], opcoes).length > 0 ? 'personalizacoes' : 'linha',
  };
};

function BlocoRazoes({ razoes }) {
  if (razoes.length === 0) return null;
  return (
    <div className="flex items-start gap-2 rounded-lg bg-destructive/10 text-destructive p-3 text-sm">
      <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
      <div className="space-y-0.5">
        {razoes.map((razao, i) => <p key={`${i}-${razao}`}>{razao}</p>)}
      </div>
    </div>
  );
}

function Seccao({ titulo, children }) {
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-muted-foreground">{titulo}</h3>
      {children}
    </section>
  );
}

// O diálogo do produto (Plano 2C, Task 3, do print do Vendus): SUBSTITUI o
// painel direito da conta, não é um modal por cima dela. Como o PosEntrar,
// enche o espaço que o pai lhe der (`h-full`) e nunca assume que é a página
// inteira — quem decide isso é o PosVenda.
export default function PosDialogoProduto({ produto, grupos, linha, aGravar, onGravar, onVoltar, onRemover }) {
  // O pai pode manter este componente montado e trocar-lhe o produto por
  // baixo (tocar noutra linha da conta sem passar pela grelha). Sem repor o
  // estado, o ecrã mostrava o nome do artigo novo com a quantidade, o preço e
  // os toppings do anterior. A dependência é a dos IDS e não a dos objectos:
  // a `venda` que volta do servidor traz objectos novos com os mesmos ids, e
  // repor aí apagava o que a operadora tinha acabado de escrever.
  const chave = `${produto?.id || ''}|${linha?.id || ''}`;
  // A base fiscal e os valores iniciais saem do MESMO cálculo, guardado com a
  // MESMA chave — e não de dois `useMemo` a correr por sua conta. É o que
  // garante que o preço/IVA que o ecrã mostra e o preço/IVA contra o qual se
  // decide o override são, literalmente, o mesmo valor.
  const arranque = useMemo(() => {
    const base = baseDaLinha(produto, linha);
    return { ...valoresIniciais(produto, linha, grupos, base), base };
  }, [chave]); // eslint-disable-line react-hooks/exhaustive-deps

  const [quantidade, setQuantidade] = useState(arranque.quantidade);
  const [preco, setPreco] = useState(arranque.preco);
  const [taxa, setTaxa] = useState(arranque.taxa);
  const [descontoPct, setDescontoPct] = useState(arranque.descontoPct);
  const [descontoEur, setDescontoEur] = useState(arranque.descontoEur);
  const [opcoes, setOpcoes] = useState(arranque.opcoes);
  const [vista, setVista] = useState(arranque.vista);

  useEffect(() => {
    setQuantidade(arranque.quantidade);
    setPreco(arranque.preco);
    setTaxa(arranque.taxa);
    setDescontoPct(arranque.descontoPct);
    setDescontoEur(arranque.descontoEur);
    setOpcoes(arranque.opcoes);
    setVista(arranque.vista);
  }, [arranque]);

  // As duas leituras da selecção vêm do MESMO sítio que o painel usa, e é de
  // propósito: uma linha montada no pedido guiado chega aqui com doses (a
  // Nutella repetida) e com um grupo de texto no produto, e este ecrã já a
  // recusou por causa das duas coisas — "Em Fruta pode escolher no máximo 2."
  // a olhar para Morango 3× + Kiwi 1×, e "Nome exige 1 escolha mas não tem
  // nenhuma opção disponível — avise o gestor" a olhar para um grupo que nunca
  // teve opções. Com o Gravar desligado, aquela linha ficava sem desconto, sem
  // quantidade e sem preço: só se podia apagar e picar de novo. As duas regras
  // (contar opções diferentes, ignorar os grupos de texto) vivem hoje dentro
  // do `errosDeSelecao`, para nenhum chamador as poder esquecer outra vez.
  const errosSelecao = useMemo(() => errosDeSelecao(grupos || [], opcoes), [grupos, opcoes]);
  const resumo = resumoDaSelecao(opcoes);

  // O nome vem do retrato pela mesma razão que o preço e o IVA: é o
  // `linha.produto_nome` que `precos.linha_de_venda` põe no título que sai no
  // talão. Com o nome do catálogo, um artigo renomeado a meio do dia aparecia
  // aqui com o nome novo e saía no papel com o antigo — e era o papel que a
  // cliente tinha na mão a discutir. Só numa linha nova (ou num retrato sem
  // nome) é que se olha para o catálogo.
  const nome = (linha ? linha.produto_nome || produto?.nome : produto?.nome) || 'Produto';

  // Preencher um limpa o outro. Não é decoração: o Vendus só aceita UM
  // desconto por linha e o servidor resolve o empate com o € a ganhar
  // (`precos.linha_de_venda`). Deixar os dois campos cheios ao mesmo tempo
  // convidava a operadora a somá-los de cabeça e a dar um desconto que a
  // fatura ia ignorar em silêncio.
  const mudarDescontoEur = (texto) => {
    setDescontoEur(texto);
    if (texto !== '') setDescontoPct('');
  };
  const mudarDescontoPct = (texto) => {
    const limpo = aceitarNumero(texto);
    setDescontoPct(limpo);
    if (limpo !== '') setDescontoEur('');
  };

  const qtdNumero = /^\d+$/.test(quantidade) ? Number(quantidade) : null;
  const precoNumero = numeroOuNulo(preco);
  const pctNumero = numeroOuNulo(descontoPct);
  const eurNumero = numeroOuNulo(descontoEur);

  const precoValido = precoNumero !== null && precoNumero >= 0 && !temMaisDe2CasasDecimaisPos(preco);
  const eurValido = eurNumero === null || (eurNumero >= 0 && !temMaisDe2CasasDecimaisPos(descontoEur));
  const pctValida = pctNumero === null || (pctNumero >= 0 && pctNumero <= 100 && !temMaisDe2CasasDecimaisPos(descontoPct));

  // A MESMA ordem de `precos.linha_de_venda`: as opções somam ao preço
  // unitário, o resultado é que multiplica pela quantidade, e só depois entra
  // o desconto. Somar o desconto antes da quantidade dava outro número — e
  // seria esse o que a operadora via, contra o que sai no papel.
  const extraOpcoes = (opcoes || []).reduce((soma, o) => soma + (Number(o?.preco) || 0), 0);
  const precoUnitario = cent((precoNumero || 0) + extraOpcoes);
  const brutoLinha = cent(precoUnitario * (qtdNumero || 0));
  // Truthiness, e não `!== null`, porque é assim que o servidor decide
  // (`if desconto_eur: ... elif desconto_pct:`): um desconto de 0 € não é um
  // desconto, e deixa passar a percentagem.
  const descontoLinha = eurNumero ? eurNumero : (pctNumero ? cent(brutoLinha * pctNumero / 100) : 0);
  const totalLinha = cent(brutoLinha - descontoLinha);

  const razoes = [];
  // Um produto mal configurado não entra na conta, e nenhum override o
  // contorna: `venda.py::juntar_linha` corre `erros_do_produto` sobre o
  // PRODUTO DO CATÁLOGO antes de sequer olhar para o preço ou o IVA que este
  // ecrã enviar. Recusar aqui é dizer-lhe a mesma coisa sem o cliente à
  // frente e sem um 422 pelo caminho.
  if (produto && produto.vendavel === false) {
    (produto.erros && produto.erros.length ? produto.erros : ['Este produto não pode ser vendido.'])
      .forEach((e) => razoes.push(e));
  }
  // Sem IVA não há venda (é a regra de ouro do `precos.py`, que recusa a linha
  // com 422). A `taxa` só fica vazia quando NEM o retrato da linha NEM o
  // produto trazem `tax_id`; num produto do catálogo mal configurado isso já
  // vem dito por `erros`, logo acima, e não se repete a mesma queixa duas
  // vezes no mesmo bloco vermelho.
  if (!taxa && !(produto && produto.vendavel === false)) {
    razoes.push('Esta linha não tem IVA definido — escolha a taxa antes de gravar.');
  }
  if (qtdNumero === null || qtdNumero < 1) razoes.push('A quantidade tem de ser pelo menos 1.');
  if (preco === '') razoes.push('Falta o preço unitário.');
  else if (precoNumero === null || precoNumero < 0) razoes.push('O preço unitário não é um valor válido.');
  if (pctNumero !== null && pctNumero > 100) razoes.push('O desconto em percentagem não pode passar de 100%.');
  // O servidor recusa isto com esta mesma razão (`precos.linha_de_venda`) —
  // mas aqui já se sabe o valor da linha, e é melhor dizê-lo enquanto ela
  // escreve do que devolver-lhe um 422 depois de carregar em Gravar. Só se
  // compara com a quantidade e o preço já válidos: com um deles por
  // preencher, `brutoLinha` é 0 e isto acusava o desconto de um problema que
  // é do campo ao lado. Um bruto de 0 € com preço e quantidade certos (um
  // artigo a zero) entra no teste na mesma — é aí que qualquer desconto o
  // torna negativo.
  if (qtdNumero !== null && precoValido && eurNumero !== null && eurValido && eurNumero > brutoLinha) {
    razoes.push(
      `O desconto de ${euros(eurNumero)} é maior do que esta linha (${euros(brutoLinha)}) — ` +
      'produziria uma linha negativa numa fatura real.'
    );
  }
  errosSelecao.forEach((e) => razoes.push(e));

  const podeGravar = razoes.length === 0 && precoValido && eurValido && pctValida && !aGravar;

  const gravar = () => {
    if (!podeGravar) return;
    // As seis chaves vão SEMPRE, mesmo a null: o `PedidoEditarLinha` lê-se com
    // `model_dump(exclude_unset=True)`, por isso uma chave que não vá não é
    // "limpar", é "deixar como estava" — e um desconto tirado no ecrã ficava
    // na linha na mesma.
    onGravar({
      quantidade: qtdNumero,
      opcoes,
      // Só viaja se for DIFERENTE do que o servidor já cobra por esta linha
      // (`arranque.base`: o retrato dela, ou o catálogo se a linha é nova).
      // Mandar sempre o preço funcionava hoje e congelava na linha um valor
      // que deixava de acompanhar o catálogo — e, no histórico, ninguém
      // voltava a saber se naquela venda houve mesmo um ajuste manual ou não.
      // Comparar com o catálogo em cache era pior: num artigo cujo preço mudou
      // depois de este PC arrancar, o preço que ela reescrevia à mão era
      // descartado como "sem override" e a conta continuava noutro valor.
      preco_override: precoNumero !== null && precoNumero !== arranque.base.preco ? precoNumero : null,
      // Mesma regra e MESMA base para o IVA — aqui não é só dinheiro, é o
      // imposto que sai na Fatura Simplificada.
      tax_override: taxa && taxa !== arranque.base.taxa ? taxa : null,
      desconto_pct: pctNumero,
      desconto_eur: eurNumero,
    });
  };

  if (vista === 'personalizacoes') {
    return (
      <div className="flex h-full flex-col bg-card">
        <header className="flex items-center gap-3 border-b p-3 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-12 w-12 shrink-0"
            onClick={() => setVista('linha')}
            aria-label="Voltar ao produto"
          >
            <ArrowLeft className="h-6 w-6" />
          </Button>
          <div className="min-w-0">
            <p className="font-heading font-bold text-lg leading-tight">Personalizações</p>
            <p className="text-xs text-muted-foreground truncate">{nome}</p>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 min-h-0">
          <PosPersonalizacoes grupos={grupos} seleccionadas={opcoes} onChange={setOpcoes} />
        </div>

        <div className="border-t p-4 space-y-3 shrink-0">
          <BlocoRazoes razoes={errosSelecao} />
          {/* Concluir volta ao produto, não grava nada — o que fica por
              escolher volta a aparecer lá em baixo, ao lado do Gravar. Prender
              a operadora aqui até a selecção estar certa tirava-lhe a
              hipótese de ir ver o total ou de simplesmente desistir. */}
          <Button className="w-full h-14 text-base" onClick={() => setVista('linha')}>
            Concluir
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-card">
      <header className="flex items-center gap-3 border-b p-3 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          className="h-12 w-12 shrink-0"
          onClick={onVoltar}
          disabled={aGravar}
          aria-label="Voltar à conta"
        >
          <ArrowLeft className="h-6 w-6" />
        </Button>
        {produto?.foto_url && (
          <img src={produto.foto_url} alt="" className="h-12 w-12 rounded-lg object-cover shrink-0" />
        )}
        <div className="min-w-0">
          <p className="font-heading font-bold text-lg leading-tight truncate">{nome}</p>
          <p className="text-xs text-muted-foreground">{linha ? 'Linha da conta' : 'A juntar à conta'}</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-4 space-y-6 min-h-0">
        <Seccao titulo="Quantidade">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setQuantidade(String(Math.max(1, (qtdNumero || 1) - 1)))}
              disabled={aGravar || (qtdNumero || 1) <= 1}
              aria-label="Menos um"
              className="h-16 w-16 shrink-0 rounded-2xl border bg-card flex items-center justify-center hover:bg-accent active:scale-[0.96] transition-transform disabled:opacity-50"
            >
              <Minus className="h-6 w-6" />
            </button>
            <Input
              id="quantidade-linha"
              value={quantidade}
              onChange={(e) => setQuantidade(e.target.value.replace(/[^0-9]/g, ''))}
              inputMode="numeric"
              disabled={aGravar}
              aria-label="Quantidade"
              className="h-16 text-3xl font-heading font-bold text-center"
            />
            <button
              type="button"
              onClick={() => setQuantidade(String((qtdNumero || 0) + 1))}
              disabled={aGravar}
              aria-label="Mais um"
              className="h-16 w-16 shrink-0 rounded-2xl border bg-card flex items-center justify-center hover:bg-accent active:scale-[0.96] transition-transform disabled:opacity-50"
            >
              <Plus className="h-6 w-6" />
            </button>
          </div>
        </Seccao>

        <div className="grid grid-cols-1 sm:grid-cols-[1fr_8rem] gap-3 items-start">
          <PosCampoValor
            id="preco-linha"
            label="Preço Unitário"
            valor={preco}
            onChange={setPreco}
            disabled={aGravar}
          />
          <div className="space-y-1.5">
            <label htmlFor="iva-linha" className="text-sm font-medium">IVA</label>
            <Select value={taxa} onValueChange={setTaxa} disabled={aGravar}>
              <SelectTrigger id="iva-linha" className="h-16 text-xl font-heading font-bold">
                <SelectValue placeholder="—" />
              </SelectTrigger>
              <SelectContent>
                {TAXAS_IVA.map((t) => (
                  <SelectItem key={t.codigo} value={t.codigo} className="text-base py-3">
                    {t.etiqueta}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <Seccao titulo="Desconto a aplicar">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-start">
            <div className="space-y-1.5">
              <label htmlFor="desconto-pct" className="text-sm font-medium">Em percentagem</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 text-2xl font-heading font-bold text-muted-foreground pointer-events-none">
                  %
                </span>
                <Input
                  id="desconto-pct"
                  value={descontoPct}
                  onChange={(e) => mudarDescontoPct(e.target.value)}
                  inputMode="decimal"
                  disabled={aGravar}
                  placeholder="0"
                  className="h-16 pl-11 pr-4 text-3xl font-heading font-bold text-right"
                />
              </div>
              {!pctValida && (
                <p className="text-xs text-destructive">
                  {pctNumero !== null && pctNumero > 100
                    ? 'Não pode passar de 100%.'
                    : 'Não pode ter mais de 2 casas decimais.'}
                </p>
              )}
            </div>
            <PosCampoValor
              id="desconto-eur"
              label="Em euros"
              valor={descontoEur}
              onChange={mudarDescontoEur}
              disabled={aGravar}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Só um dos dois — preencher um limpa o outro. Na fatura, uma linha leva um único
            desconto e o € tem precedência sobre a %.
          </p>
        </Seccao>

        {/* Também quando o produto já não tem grupos NENHUNS mas a linha traz
            opções: é o caso de o gestor ter desactivado o grupo (ou o próprio
            artigo) com a conta aberta. Essas opções continuam a somar ao preço
            unitário no servidor, e só por aqui é que se lhes chega para as
            retirar — com a condição a olhar só para os `grupos`, a secção
            desaparecia e a operadora ficava com um "+ 0,95 €" na linha sem
            nenhuma forma de o tirar. O PosPersonalizacoes já as mostra como
            "Personalizações fora do catálogo", com um X em cada uma. */}
        {((grupos && grupos.length > 0) || opcoes.length > 0) && (
          <Seccao titulo="Personalizações">
            <Button
              variant="outline"
              className={`w-full h-14 text-base justify-start ${errosSelecao.length > 0 ? 'border-destructive/50' : ''}`}
              onClick={() => setVista('personalizacoes')}
              disabled={aGravar}
            >
              <SlidersHorizontal className="h-5 w-5 mr-2" />
              Editar Personalizações
            </Button>
            <p className="text-sm text-muted-foreground">
              {resumo || 'Sem personalizações escolhidas.'}
            </p>
          </Seccao>
        )}

        {onRemover && (
          // Longe do Gravar de propósito: são as duas acções que fecham este
          // ecrã, e a que apaga uma linha da conta não pode estar ao lado da
          // que a grava, no canto onde a mão vai por hábito.
          <Button
            variant="outline"
            className="w-full h-14 text-base text-destructive border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
            onClick={onRemover}
            disabled={aGravar}
          >
            <Trash2 className="h-5 w-5 mr-2" />
            Remover da conta
          </Button>
        )}
      </div>

      <div className="border-t p-4 space-y-3 shrink-0">
        <BlocoRazoes razoes={razoes} />
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total da linha</p>
            {/* Estimativa para ela decidir enquanto o diálogo está aberto.
                Depois de Gravar, o que vale é o `venda.totais` do servidor —
                este ecrã nunca soma nada que sirva de total da conta. */}
            <p className="text-3xl font-heading font-bold tabular-nums truncate">{euros(totalLinha)}</p>
          </div>
          <Button
            size="lg"
            className="h-16 px-10 text-lg shrink-0"
            onClick={gravar}
            disabled={!podeGravar}
          >
            {aGravar ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Gravar'}
          </Button>
        </div>
      </div>
    </div>
  );
}
