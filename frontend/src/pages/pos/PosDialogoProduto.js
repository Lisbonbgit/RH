import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ArrowLeft, Loader2, Minus, Pencil, Plus, SlidersHorizontal, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import PosCampoValor from './PosCampoValor';
import PosPersonalizacoes, {
  ehIndicacaoDeServico, errosDeSelecao, resumoDaSelecao,
} from './PosPersonalizacoes';
import { arredondarComoOServidor, temMaisDe2CasasDecimaisPos } from '@/lib/pos';

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
// `precos.linha_de_venda` e `venda.py::_totais` — não uma vez no fim.
//
// **Vem de `lib/pos.js`, e não escrito outra vez aqui.** Era
// `Math.round(valor * 100) / 100`, com um comentário a dar por inevitável a
// divergência de um cêntimo num desconto em percentagem que caísse a meio.
// Não era inevitável, era só outro arredondamento: medido no browser, um
// artigo de 7,15 € com −10 % escrevia **TOTAL DA LINHA € 6,43** neste
// diálogo, e o servidor gravava a linha a 6,44 €.
//
// **O que difere entre este ecrã e o `contasDaLinha` é a ENTRADA, não a
// ordem.** Aqui esteve escrito que "a ORDEM das contas é diferente em cada
// ecrã de propósito", e não é: os quatro passos abaixo são, um a um, os do
// `contasDaLinha` e os do `precos.linha_de_venda` — opções somam ao unitário,
// o unitário multiplica pela quantidade, o desconto entra por último, com
// `round` a cada passo. O que é diferente é de onde vêm os números: este lê
// CAMPOS DE TEXTO a meio de serem escritos (um preço apagado, uma
// percentagem por acabar), o `contasDaLinha` lê uma linha que o servidor já
// aceitou. Escrever "a ordem é diferente" era dar licença à próxima
// alteração para a mudar — e foi exactamente uma frase assim, sobre o
// arredondamento, que autorizou o cêntimo de divergência que acabou de ser
// corrigido.
//
// O número que manda depois de Gravar continua a ser o `venda.totais` do
// servidor, e nunca este: aqui não há sequer conta ainda.
const cent = arredondarComoOServidor;

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

// O pedido de uma linha já gravada, em TRÊS campos rotulados — para o bloco
// só de leitura no topo deste diálogo (Task 7, brief da faturação): a mesma
// leitura do `talao.pedido_da_cozinha` (SERVIÇO / NOME no copo / o resto),
// só que aqui SEPARADOS, ao contrário do `resumoDoPedido` do
// `PosPedidoGuiado` — esse junta Serviço e Nome numa frase só (é o que cabe
// na conta), mas aqui, no ecrã onde ela decide se toca em "Editar pedido",
// Serviço e Nome são coisas diferentes e ela corrige-as por razões
// diferentes (ver o "Porquê" do brief).
//
// A DIVISÃO das opções é a mesma do `resumoDoPedido` e vem agora da mesma
// função que ele usa (`ehIndicacaoDeServico`) — o que é repetido aqui é só a
// arrumação em três campos. Enquanto cada ecrã tinha a sua leitura, os dois
// tinham o mesmo defeito escrito duas vezes: uma opção PAGA de um grupo com o
// interruptor desligado caía em "Serviço", dita uma vez e sem dose, enquanto a
// Fatura Simplificada lhe somava as duas doses e as escrevia no título.
const tituloDoPedido = (linha) => {
  const opcoes = (Array.isArray(linha?.opcoes) ? linha.opcoes : []).filter(Boolean);
  const respostas = (Array.isArray(linha?.respostas_texto) ? linha.respostas_texto : []).filter(Boolean);

  const servico = [];
  opcoes.forEach((o) => {
    if (!ehIndicacaoDeServico(o) || !o.nome) return;
    const nome = String(o.nome);
    if (!servico.includes(nome)) servico.push(nome);
  });

  // O nome que vai no copo é a PRIMEIRA resposta de texto não vazia — a
  // mesma regra do `talao._nome_no_copo`, porque é o texto que sai no papel
  // que a operadora tem na mão.
  let nome = '';
  for (let i = 0; i < respostas.length && !nome; i += 1) {
    const texto = String(respostas[i]?.texto || '').trim();
    if (texto) nome = texto;
  }

  const doses = new Map();
  opcoes.forEach((o) => {
    if (ehIndicacaoDeServico(o) || !o.nome) return;
    const chave = String(o.nome);
    doses.set(chave, (doses.get(chave) || 0) + 1);
  });
  // A dose aparece SEMPRE, mesmo a 1× — a mesma razão do `resumoDoPedido`: o
  // número é para se conferir de relance quantas colheres foram pedidas.
  const personalizacoes = Array.from(doses, ([n, quantas]) => `${n} ${quantas}×`).join(', ');

  return [
    { label: 'Serviço', valor: servico.join(' · ') },
    { label: 'Nome', valor: nome },
    { label: 'Personalizações', valor: personalizacoes },
  ].filter((p) => p.valor);
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
export default function PosDialogoProduto({
  produto, grupos, linha, aGravar, onGravar, onVoltar, onRemover, onEditarPedido,
}) {
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
  // Há uma edição de `opcoes` feita no painel de Personalizações de sempre
  // (mais abaixo) que ainda não foi gravada nesta linha — ver o guarda do
  // efeito de resincronização a seguir, e a razão de este estado existir.
  const [opcoesPorGravar, setOpcoesPorGravar] = useState(false);

  useEffect(() => {
    setQuantidade(arranque.quantidade);
    setPreco(arranque.preco);
    setTaxa(arranque.taxa);
    setDescontoPct(arranque.descontoPct);
    setDescontoEur(arranque.descontoEur);
    setOpcoes(arranque.opcoes);
    setVista(arranque.vista);
    setOpcoesPorGravar(false);
  }, [arranque]);

  // "Editar pedido" (Task 7) grava directamente no servidor — `editarLinha`,
  // chamado pelo `PosPedidoGuiado` que este ecrã reabre por cima de si
  // próprio — sem passar pelo Gravar aqui embaixo. A `linha` que volta já
  // tem as opções novas, mas a `chave` não muda (é a MESMA linha, de
  // propósito — ver o comentário dela acima), por isso o estado local
  // `opcoes` não se repunha sozinho. Sem este efeito, a Nutella que acabou
  // de sair do pop-up ficava ausente do Total desta linha, e o PRÓPRIO
  // Gravar deste ecrã — que manda `opcoes` sempre, mais abaixo — desfazia a
  // correcção ao gravar por cima o valor antigo.
  //
  // O guarda de baixo NÃO É `vista === 'personalizacoes'` sozinho — foi,
  // até um achado da revisão da Task 7 mostrar que isso é uma garantia
  // falsa. "Concluir", no painel de Personalizações, NÃO grava — devolve
  // `vista` a 'linha' e a edição fica pendurada em `opcoes`, por gravar.
  // Nesse estado, o "Editar pedido" já não tinha guarda nenhum: o cenário
  // real é uma opção órfã (o gestor desactivou o grupo dela com a conta
  // aberta) que a operadora retira no painel de sempre, "Concluir", e só
  // DEPOIS se lembra de reabrir "Editar pedido" para outra coisa — o
  // pop-up semeia-se a partir da `linha` (a verdade do servidor, que ainda
  // tem a opção órfã, porque "Concluir" nunca a gravou), grava por cima com
  // `editarLinha`, e este efeito devolvia a opção órfã e o preço dela à
  // linha, em silêncio, apagando exactamente a correcção que a operadora
  // acabara de fazer. `opcoesPorGravar` é o que falta: fica verdadeiro
  // assim que o painel muda `opcoes` (ver o `onChange` mais abaixo) e só
  // volta a falso quando a `chave` muda (uma linha ou um produto novos) —
  // sobrevive ao "Concluir" de propósito, ao contrário de `vista`. O botão
  // "Editar pedido" fica desligado enquanto isto for verdade (mais abaixo),
  // por isso as duas edições deixam mesmo de poder correr ao mesmo tempo —
  // agora é verdade, e não só a intenção do comentário antigo.
  useEffect(() => {
    if (vista === 'personalizacoes' || opcoesPorGravar) return;
    setOpcoes(Array.isArray(linha?.opcoes) ? linha.opcoes.filter(Boolean) : []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linha]);

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

  // O bloco de leitura do topo (Task 7) e o botão que o acompanha. Sai da
  // LINHA (a verdade do servidor), nunca do `opcoes` local — o bloco lê-se
  // enquanto o estado local pode estar a meio de ser reposto pelo efeito
  // acima, e mostrar aí um valor a piscar era pior do que ler sempre a
  // mesma fonte que o "Editar pedido" também usa para semear o pop-up.
  const titulo = tituloDoPedido(linha);

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
          {/* `opcoesPorGravar` marca-se aqui, e só aqui — é a ÚNICA maneira
              de `opcoes` mudar fora do arranque e da resincronização do
              "Editar pedido" (ver o efeito acima). Sem isto, uma opção
              retirada aqui e nunca gravada não deixava rasto nenhum. */}
          <PosPersonalizacoes
            grupos={grupos}
            seleccionadas={opcoes}
            onChange={(novas) => { setOpcoes(novas); setOpcoesPorGravar(true); }}
          />
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
        {/* O bloco de leitura do pedido guiado (Task 7, brief da faturação).
            Só aparece quando HÁ um pedido guiado para reabrir — um produto
            sem grupos (ou sem `onEditarPedido`, o que o pai só omite quando
            não há linha nenhuma para editar) não tem passo nenhum para
            mostrar, e um "Editar pedido" que abrisse um pop-up vazio era um
            botão morto. Fica ANTES da Quantidade de propósito: é o resumo
            que ela confere com o cliente antes de mexer em preço ou
            desconto — a mesma ordem de leitura do talão da cozinha. */}
        {grupos && grupos.length > 0 && onEditarPedido && (
          <div className="rounded-2xl border bg-muted/40 p-3 space-y-2.5">
            <p className="text-sm leading-snug">
              {titulo.length > 0 ? titulo.map((p, i) => (
                <React.Fragment key={p.label}>
                  {i > 0 && ' · '}
                  <strong className="font-heading">{p.label}</strong> {p.valor}
                </React.Fragment>
              )) : 'Sem pedido registado.'}
            </p>
            <Button
              variant="outline"
              className="w-full h-12 text-base justify-start"
              onClick={onEditarPedido}
              disabled={aGravar || opcoesPorGravar}
            >
              <Pencil className="h-5 w-5 mr-2" />
              Editar pedido
            </Button>
            {/* Explica o desligado, e não só o desliga — a mesma regra do
                "Porquê" do brief desta tarefa: um caminho que fica sem saída
                sem dizer porquê é o defeito que a Task 7 existe para evitar,
                só que agora aplicado a este botão. Carregar em Gravar (em
                baixo) resolve: grava a alteração pendente e fecha a linha —
                reabri-la já deixa "Editar pedido" outra vez disponível. */}
            {opcoesPorGravar && (
              <p className="text-xs text-muted-foreground">
                Há uma alteração em Personalizações por gravar. Carregue em Gravar, em baixo,
                antes de editar o pedido outra vez.
              </p>
            )}
          </div>
        )}

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
