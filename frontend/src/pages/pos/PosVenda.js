import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  AlertCircle, Ban, ChevronLeft, ChevronRight, EyeOff, ImageOff, Loader2, MoreHorizontal,
  Printer, Search, ShoppingCart, Trash2, X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle,
  AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction,
} from '@/components/ui/alert-dialog';
import PosDialogoProduto from './PosDialogoProduto';
import PosFinalizar from './PosFinalizar';
import { errosDeSelecao, resumoDaSelecao } from './PosPersonalizacoes';
import {
  getCatalogoPos, getTiposPagamentoPos, getVendaAberta, abrirVenda, juntarLinha,
  editarLinha, removerLinha, aplicarDescontoGlobal, cancelarVenda, finalizarVenda,
  detalhesErroPos, semRespostaPos, ehTimeoutPos, TIMEOUT_PADRAO_MS,
} from '@/lib/pos';

// O ecrã de venda do POS (Plano 2C, Tasks 3 e 4, dos prints do Vendus): a
// grelha de produtos à esquerda, a conta à direita.
//
// Três regras mandam neste ficheiro, e todas as outras decisões saem delas:
//
//   1. **Os totais vêm SEMPRE do servidor** (`venda.totais`). Todas as rotas
//      de venda devolvem a conta inteira já somada; a resposta de cada
//      chamada É a verdade e substitui o estado. Se o ecrã somasse por sua
//      conta, o número que a operadora lê e o que sai no papel podiam
//      divergir ao cêntimo — e seria o papel a ter razão.
//   2. **A conta só nasce ao PRIMEIRO produto.** Nunca ao montar o ecrã:
//      abrir a venda no arranque criava uma conta vazia por cada F5 e por
//      cada vez que a tela de descanso caísse, e `fat_vendas` enchia-se de
//      órfãs para sempre (ver a docstring de `venda.py::venda_aberta`).
//   3. **Nada desaparece do ecrã em silêncio** — o mesmo fio condutor do
//      `pos_catalogo.py`: um produto mal configurado aparece morto e com a
//      razão à vista, e um botão que ainda não faz nada diz porquê.

const POR_PAGINA = 20; // 5 por linha × 4 linhas, a grelha do print

// Os segundos do tecto de espera do lib/pos.js, para as mensagens poderem
// dizer o número em vez de um "demorou" vago. Vem de lá e não escrito à mão
// aqui: dois sítios com o mesmo número acabam sempre com o ecrã a prometer
// uma espera que já não é a real.
const SEGUNDOS_DE_ESPERA = Math.round(TIMEOUT_PADRAO_MS / 1000);

// Ao fim de quanto tempo o ecrã de arranque deixa de ser só um spinner. Não
// é o timeout (esse desiste sozinho e mostra o erro com "Tentar novamente"):
// é o momento em que uma espera normal passa a parecer um ecrã encravado, e
// a operadora merece saber que ainda está a acontecer alguma coisa e ter um
// botão à frente em vez de descobrir o F5 por sua conta.
const MS_ATE_AVISAR_ESPERA = 6000;

const euros = (valor) =>
  `€ ${(Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const cent = (valor) => Math.round(valor * 100) / 100;

// Sem acentos e em minúsculas: ao balcão escreve-se "acai" e o produto
// chama-se "Açaí". Uma pesquisa que só casasse a acentuação exacta era uma
// pesquisa que nunca encontrava nada com pressa em cima.
const semAcentos = (texto) =>
  String(texto || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

// A mensagem EXACTA de `venda.py::_MSG_VENDA_NAO_ABERTA`. É preciso
// RECONHECÊ-LA, e não só mostrá-la (o mesmo raciocínio do
// MSG_DISPOSITIVO_INVALIDO em lib/pos.js): um 409 com esta frase quer dizer
// que o ecrã ficou para trás — a conta foi emitida ou cancelada noutro sítio
// — e o que há a fazer é recarregar, não insistir. Se um dia o texto do
// servidor mudar, isto deixa de casar e o erro cai no caminho genérico, que
// mostra à mesma a frase do servidor: degrada, não mente.
const MSG_VENDA_NAO_ABERTA = 'Esta venda já foi emitida ou cancelada — não aceita alterações.';

// O total de uma linha JÁ GRAVADA, na MESMA ordem de `precos.linha_de_venda`:
// as opções somam ao preço unitário, o resultado multiplica pela quantidade,
// e só depois entra o desconto (com `round` a cada passo, como o servidor).
//
// É uma estimativa de LEITURA, para a coluna "Preço" do print — nunca um
// total da conta: esse é o `venda.totais.total` do servidor, e é ele que
// aparece na faixa. A única divergência possível é um cêntimo num desconto em
// % que caia exactamente a meio (o Python arredonda para o par, o JavaScript
// para cima), e por isso a soma destas linhas nunca é mostrada em lado nenhum.
//
// O `PosDialogoProduto` tem a sua própria versão desta conta de propósito: a
// dele trabalha sobre campos de texto a meio de serem escritos, esta trabalha
// sobre uma linha que o servidor já aceitou.
const contasDaLinha = (linha) => {
  const base = linha.preco_override != null ? linha.preco_override : linha.produto_preco;
  const extra = (linha.opcoes || []).reduce((soma, o) => soma + (Number(o?.preco) || 0), 0);
  const unitario = cent((Number(base) || 0) + extra);
  const bruto = cent(unitario * (Number(linha.quantidade) || 0));
  // Truthiness, como o servidor (`if desconto_eur: ... elif desconto_pct:`):
  // um desconto de 0 € não é desconto e deixa passar a percentagem.
  const desconto = linha.desconto_eur
    ? Number(linha.desconto_eur)
    : (linha.desconto_pct ? cent(bruto * Number(linha.desconto_pct) / 100) : 0);
  return { unitario, bruto, desconto, total: cent(bruto - desconto) };
};

// Em que balde do PosFinalizar cai um erro da emissão. A regra que manda
// aqui: **só se diz "nada saiu" quando o servidor o disse**. Um balde errado
// não é um texto errado — é o ecrã a convidar a mexer numa venda que pode
// estar, nesse instante, a virar uma Fatura Simplificada real.
//
//   422 → 'dados'. O ÚNICO caso em que "há algo por corrigir nesta venda" é
//     verdade. `fiscal.py::finalizar` corre TODA a validação (linhas, total
//     positivo, pagamentos a bater com o total, tipos mapeados no Vendus)
//     ANTES de tocar na reserva atómica: o pedido morreu antes de sair para
//     a rede, nada foi ao Vendus, e corrigir e repetir é seguro.
//
//   502 → 'vendus'. Ou é configuração recusada antes de qualquer pedido
//     (conta Vendus/register_id em falta), ou é o `VendusErro` de um Vendus
//     que respondeu mal ou não respondeu — e nesse ramo `_emitir_e_gravar`
//     LIBERTA a reserva, ou seja, o servidor sabe que não criou documento
//     nenhum. Repetir é seguro.
//
//   503 → depende da frase, e é a única leitura de texto que aqui se faz:
//     `finalizar` devolve 503 logo à cabeça quando o ÍNDICE DE IDEMPOTÊNCIA
//     não está confirmado no arranque — aí nada chegou sequer a ir ao
//     Vendus, e mostrar "não sabemos se a fatura saiu" punha a loja inteira
//     a chamar o gestor por causa de uma fatura que nunca existiu, a cada
//     venda, porque a causa é de configuração e não passa sozinha. O outro
//     503 é o `VerificacaoFiscalIncerta`, que é o incerto a sério.
//
//   TUDO O RESTO → 'incerto'. Não é preguiça, é a única coisa honesta:
//
//     · sem `response` (status `undefined`) — o Wi-Fi piscou, o pedido nunca
//       chegou, a resposta perdeu-se, ou estourou o nosso tecto de espera de
//       90 s. O nosso timeout não cancela nada do lado do servidor: o POST
//       ao Vendus continua a correr. O ecrã não sabe nada.
//     · 504 — um proxy cortou porque a emissão demorou; do outro lado o
//       servidor continua muito provavelmente a emitir.
//     · 500 — nesta rota é o `ConflitoDocumentoFiscal`: o Vendus DEVOLVEU um
//       documento fiscal real que colidiu ao gravar, e a reserva foi mantida
//       de propósito precisamente porque o documento existe. Chamar a isto
//       "há algo por corrigir na conta" é o oposto exacto da verdade.
//
// O que estava aqui mandava todos estes para 'dados'. E 'dados' não é só uma
// frase errada: é um painel que deixa a conta e os pagamentos editáveis e o
// EMITIR aceso, ou seja, convida a MUDAR o que já viajou na primeira
// tentativa. O caso real: 504 aos 30 s com o servidor a emitir; ela troca
// Dinheiro por Multibanco e carrega outra vez; o segundo pedido perde a
// reserva e recebe o documento do vencedor — gravado com Dinheiro, enquanto
// o cliente passou o cartão. No fecho, a gaveta fica curta e ninguém percebe
// porquê. O 'incerto' é o único balde que congela o ecrã (PosFinalizar
// desliga o total, o cliente, os tipos de pagamento e o EMITIR) e manda
// chamar o gestor — que é o que se faz quando não se sabe.
const tipoDoErroDeEmissao = (status, mensagem) => {
  if (status === 422) return 'dados';
  if (status === 502) return 'vendus';
  if (status === 503) return /índice de idempotência/i.test(mensagem) ? 'vendus' : 'incerto';
  return 'incerto';
};

// --- A grelha -----------------------------------------------------------------

function Foto({ url, alt }) {
  const [partida, setPartida] = useState(false);
  // Um `foto_url` que já não responde (a imagem foi apagada do servidor)
  // desenhava o ícone de imagem partida do browser dentro do cartão. O
  // onError troca-o pelo mesmo espaço de reserva de quem nunca teve foto.
  if (!url || partida) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-muted">
        <ImageOff className="h-7 w-7 text-muted-foreground/50" />
      </div>
    );
  }
  return (
    <img
      src={url}
      alt={alt || ''}
      onError={() => setPartida(true)}
      className="w-full h-full object-cover"
    />
  );
}

function CartaoProduto({ produto, onTocar }) {
  // `vendavel: false` vem do servidor (`pos_catalogo.py`, que corre o mesmo
  // `precos.erros_do_produto` que a venda usa para recusar a linha com 422).
  // O cartão fica morto e com a razão escrita — "Sem IVA definido" é
  // precisamente a frase que a operadora repete a quem o pode corrigir.
  const vendavel = produto.vendavel !== false;

  return (
    <button
      type="button"
      onClick={() => onTocar(produto)}
      disabled={!vendavel}
      title={vendavel ? produto.nome : (produto.erros || []).join(' · ')}
      className={`text-left rounded-2xl border bg-card overflow-hidden flex flex-col transition-all ${
        vendavel
          ? 'hover:border-primary hover:shadow-md active:scale-[0.97]'
          : 'border-dashed opacity-70 cursor-not-allowed'
      }`}
    >
      <div className="aspect-square w-full overflow-hidden">
        <Foto url={produto.foto_url} alt={produto.nome} />
      </div>
      <div className="p-2.5 flex-1 flex flex-col gap-1">
        <span className="text-sm font-medium leading-tight line-clamp-2">{produto.nome}</span>
        {vendavel ? (
          <span className="font-heading font-bold text-lg tabular-nums mt-auto">
            {euros(produto.preco)}
          </span>
        ) : (
          <span className="text-xs text-destructive leading-snug mt-auto flex items-start gap-1">
            <Ban className="h-3.5 w-3.5 shrink-0 mt-px" />
            <span>{(produto.erros || []).join(' · ') || 'Não pode ser vendido'}</span>
          </span>
        )}
      </div>
    </button>
  );
}

function Paginacao({ pagina, total, onMudar }) {
  // Só aparece quando há mesmo mais do que uma página: duas setas
  // permanentemente desligadas eram o "botão morto sem dizer porquê" que o
  // resto deste ecrã evita.
  if (total <= 1) return null;
  return (
    <div className="shrink-0 border-t bg-card flex items-center justify-center gap-5 py-2">
      <button
        type="button"
        onClick={() => onMudar(pagina - 1)}
        disabled={pagina <= 0}
        aria-label="Página anterior"
        className="h-12 w-12 rounded-full border bg-card flex items-center justify-center hover:bg-accent active:scale-95 transition-transform disabled:opacity-40"
      >
        <ChevronLeft className="h-6 w-6" />
      </button>
      <span className="text-sm text-muted-foreground tabular-nums select-none">
        {pagina + 1} de {total}
      </span>
      <button
        type="button"
        onClick={() => onMudar(pagina + 1)}
        disabled={pagina >= total - 1}
        aria-label="Página seguinte"
        className="h-12 w-12 rounded-full border bg-card flex items-center justify-center hover:bg-accent active:scale-95 transition-transform disabled:opacity-40"
      >
        <ChevronRight className="h-6 w-6" />
      </button>
    </div>
  );
}

// O aviso dos artigos que o servidor não mandou. Aparece em dois tamanhos, e
// os dois são precisos: a linha discreta é para ela saber que a grelha não
// está completa mesmo sem estar a dar por falta de nada; o bloco é para o
// momento em que ESTÁ mesmo a dar pela falta — escreveu "uber", não veio
// nada, e é essa a única altura em que a pergunta "onde está o artigo?" já
// está feita e merece resposta à vista, não uma nota de rodapé.
//
// Diz sempre as três coisas: quantos são, porque não estão lá, e quem os põe
// de volta. Sem a terceira, a operadora fica a saber que falta alguma coisa
// e continua sem ter o que dizer ao gestor — que era metade do defeito.
function AvisoEscondidos({ quantos, destaque }) {
  if (!quantos) return null;
  const contagem = quantos === 1 ? '1 artigo escondido' : `${quantos} artigos escondidos`;

  if (!destaque) {
    return (
      <p className="text-xs text-muted-foreground flex items-start gap-1.5">
        <EyeOff className="h-3.5 w-3.5 shrink-0 mt-px" />
        <span>{contagem}: a categoria deles está desactivada.</span>
      </p>
    );
  }

  return (
    <div className="mx-auto max-w-md rounded-2xl border bg-muted/40 p-4 flex items-start gap-3 text-left">
      <EyeOff className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
      <div className="text-sm min-w-0">
        <p className="font-medium">{contagem}: a categoria deles está desactivada.</p>
        <p className="text-muted-foreground mt-1">
          Se o artigo que procura é um deles, não aparece aqui nem pela pesquisa. Peça ao gestor
          para reactivar a categoria no backoffice.
        </p>
      </div>
    </div>
  );
}

// --- A conta ------------------------------------------------------------------

function LinhaDaConta({ linha, onTocar }) {
  const { unitario, total, desconto } = contasDaLinha(linha);
  // A MESMA ordem e o mesmo separador que `precos.linha_de_venda` usa no
  // título que sai no talão — o ecrã e o papel nunca lêem a linha por ordens
  // diferentes.
  const opcoes = resumoDaSelecao(linha.opcoes);

  return (
    <button
      type="button"
      onClick={() => onTocar(linha)}
      className="w-full text-left grid grid-cols-[1fr_2.5rem_6rem] gap-2 items-start px-4 py-3 border-b hover:bg-accent active:scale-[0.99] transition-transform"
    >
      <div className="min-w-0">
        <p className="font-medium leading-tight">{linha.produto_nome}</p>
        {opcoes && <p className="text-xs text-muted-foreground leading-snug mt-0.5">{opcoes}</p>}
        <p className="text-xs text-muted-foreground mt-0.5 tabular-nums">
          {euros(unitario)} cada
          {desconto > 0 && ` · desconto ${euros(desconto)}`}
        </p>
      </div>
      <span className="font-heading font-bold text-lg tabular-nums text-center">{linha.quantidade}</span>
      <span className="font-heading font-bold text-lg tabular-nums text-right">{euros(total)}</span>
    </button>
  );
}

function PainelConta({ venda, aEscrever, onTocarLinha, onFinalizar, onCancelar }) {
  const linhas = venda?.linhas || [];
  const totais = venda?.totais || {};
  // "N Produtos" e "N Uni." são coisas diferentes e no print aparecem as
  // duas: produtos são LINHAS da conta, unidades é a soma das quantidades.
  const unidades = linhas.reduce((soma, li) => soma + (Number(li.quantidade) || 0), 0);

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="shrink-0 grid grid-cols-[1fr_2.5rem_6rem] gap-2 px-4 h-11 items-center border-b text-xs uppercase tracking-wide text-muted-foreground">
        <span className="flex items-center gap-2">
          Produto
          {aEscrever && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
        </span>
        <span className="text-center">Qtd</span>
        <span className="text-right">Preço</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {linhas.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6 gap-3">
            <ShoppingCart className="h-9 w-9 text-muted-foreground/40" />
            <p className="text-muted-foreground">Não existem produtos associados.</p>
            <p className="text-sm text-muted-foreground/80">
              Toque num produto à esquerda para começar a conta.
            </p>
          </div>
        ) : (
          linhas.map((linha) => (
            <LinhaDaConta key={linha.id} linha={linha} onTocar={onTocarLinha} />
          ))
        )}
      </div>

      <div className="shrink-0 px-3 pt-3">
        {/* O agente de impressão da loja é o Plano 3 e ainda não existe. O
            botão fica à vista e desligado COM A RAZÃO — a mesma regra que o
            menu Caixa já usa na gaveta e no modo de formação. Um "Imprimir"
            que não imprime nada fazia a operadora carregar três vezes e dar
            o cliente por servido sem pedido nenhum na cozinha. */}
        <Button variant="outline" className="w-full h-12 justify-start" disabled>
          <Printer className="h-5 w-5 mr-2" />
          Imprimir Pedido
          <span className="ml-auto text-[10px] uppercase tracking-wide">Brevemente</span>
        </Button>
        <p className="text-[11px] text-muted-foreground leading-snug mt-1.5">
          O pedido passa a sair na impressora quando o agente de impressão da loja existir —
          ainda não existe.
        </p>
      </div>

      <div className="shrink-0 mt-3 bg-primary text-primary-foreground px-4 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-sm font-semibold uppercase tracking-wide">Total</span>
          {/* Sempre o `venda.totais.total` do servidor — este ecrã nunca soma
              preços para os mostrar como total. */}
          <span className="font-heading font-bold text-4xl tabular-nums">{euros(totais.total)}</span>
        </div>
        <p className="text-xs text-primary-foreground/80 text-right mt-0.5 tabular-nums">
          {linhas.length} Produtos / {unidades} Uni.
        </p>
      </div>

      <div className="shrink-0 p-3 grid grid-cols-[auto_1fr] gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="h-16 px-4" aria-label="Opções da conta">
              <MoreHorizontal className="h-5 w-5 mr-1" />
              Opções
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            {/* Sem isto, uma conta que o cliente desistiu de levar ficava
                `aberta` para sempre — e era ela que o `GET /pos/venda/aberta`
                devolvia amanhã de manhã. Desligado quando não há conta
                nenhuma, mas a dizer porquê (a regra do menu Caixa). */}
            <DropdownMenuItem
              onSelect={onCancelar}
              disabled={!venda}
              className="text-destructive focus:text-destructive"
            >
              <Trash2 className="h-4 w-4 mr-2" /> Cancelar conta
              {!venda && (
                <span className="ml-auto text-[10px] text-muted-foreground">Sem conta aberta</span>
              )}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          className="h-16 text-lg font-heading font-bold"
          disabled={linhas.length === 0}
          onClick={onFinalizar}
        >
          FINALIZAR
        </Button>
      </div>
    </div>
  );
}

// --- O ecrã -------------------------------------------------------------------

export default function PosVenda({ caixa, onOperadorInvalido }) {
  // O ID da caixa, e não o objecto — e o callback do pai por trás de uma ref,
  // e não nas dependências. As duas coisas defendem a MESMA propriedade: este
  // ecrã carrega o catálogo uma vez por caixa e nunca mais. Um render do
  // PosApp com um `caixa` novo (mesmo id, objecto novo) ou com um callback
  // inline punha o `useEffect` de arranque a correr outra vez e a apagar o
  // catálogo do ecrã a meio de uma venda — e a tela de descanso, que muda o
  // operador lá em cima quando alguém desbloqueia, é exactamente um desses
  // renders. NÃO está provado por teste — o frontend deste repositório não
  // tem infraestrutura de testes nenhuma (nem jest, nem vitest, nem um só
  // ficheiro .test.js), por isso a única defesa desta regra é o cuidado de
  // quem lhe mexer: se acrescentares uma dependência a este useEffect, ou
  // passares `caixa` inteira em vez de `caixa?.id`, o catálogo volta a
  // recarregar-se a meio de uma venda e a conta desaparece do ecrã com o
  // cliente à frente. Verifica isso à mão.
  const caixaId = caixa?.id;
  const operadorInvalidoRef = useRef(onOperadorInvalido);
  useEffect(() => { operadorInvalidoRef.current = onOperadorInvalido; }, [onOperadorInvalido]);
  const operadorInvalido = useCallback(() => {
    if (operadorInvalidoRef.current) operadorInvalidoRef.current();
  }, []);

  const [carregando, setCarregando] = useState(true);
  // O arranque já passou de MS_ATE_AVISAR_ESPERA e ainda não voltou nada.
  // Não é erro (o tecto de espera é que decide isso, mais à frente): é só o
  // momento em que o spinner sozinho deixa de ser informação e passa a
  // parecer um ecrã encravado.
  const [esperaLonga, setEsperaLonga] = useState(false);
  // Conta as tentativas de carga para o temporizador acima poder recomeçar a
  // cada uma. Sem isto, o "Tentar novamente" do ecrã de espera não mudava
  // nada no ecrã: `carregarTudo` chama `setCarregando(true)` com `carregando`
  // JÁ a true, o React descarta a actualização, o efeito não volta a correr e
  // o aviso ficava colado desde a tentativa anterior — um botão que parece
  // não ter feito nada é um botão em que se carrega dez vezes.
  const [tentativaDeCarga, setTentativaDeCarga] = useState(0);
  const [erro, setErro] = useState(null);
  const [catalogo, setCatalogo] = useState({
    categorias: [], produtos: [], grupos_personalizacao: [], ocultos: 0,
  });
  const [tiposPagamento, setTiposPagamento] = useState([]);

  const [venda, setVenda] = useState(null);
  const [escritas, setEscritas] = useState(0);

  const [aba, setAba] = useState('todos');
  const [pesquisa, setPesquisa] = useState('');
  const [pagina, setPagina] = useState(0);

  // 'conta' | 'produto' | 'finalizar'. O diálogo do produto substitui o
  // PAINEL DIREITO (é o que o print manda); o finalizar toma o ecrã inteiro —
  // nesse momento não há mais nada a fazer senão receber o dinheiro, e a
  // barra do recebido/troco/EMITIR precisa da largura toda para caber numa
  // linha só.
  const [vista, setVista] = useState('conta');
  const [emEdicao, setEmEdicao] = useState(null); // { produtoId, linhaId | null }
  const [aGravar, setAGravar] = useState(false);

  const [aEmitir, setAEmitir] = useState(false);
  const [documento, setDocumento] = useState(null);
  const [erroEmissao, setErroEmissao] = useState(null);
  const [aConfirmarCancelar, setAConfirmarCancelar] = useState(false);

  // A conta também vive numa ref: `garantirVenda` corre dentro da fila de
  // escritas (abaixo) e precisa de saber se JÁ existe uma venda neste
  // instante — o `venda` do state é o de quando a função foi criada, e com
  // ele dois toques seguidos abriam duas contas.
  const vendaRef = useRef(null);
  const aplicarVenda = useCallback((nova) => {
    vendaRef.current = nova;
    setVenda(nova);
  }, []);

  // Todas as escritas da conta passam por esta fila, uma de cada vez.
  // `venda.py::juntar_linha` lê a venda, acrescenta a linha e grava o ARRAY
  // INTEIRO (`$set: {linhas}`): dois pedidos ao mesmo tempo lêem as mesmas
  // linhas e o segundo grava por cima do primeiro — o produto do primeiro
  // toque desaparecia da conta sem nada a avisar. Ao balcão toca-se
  // depressa, por isso isto não é teórico. Serializar aqui custa nada (são
  // pedidos de dezenas de milissegundos) e, ao contrário de "ignorar
  // enquanto está a gravar", não perde nenhum toque.
  const fila = useRef(Promise.resolve());
  const executar = useCallback((tarefa) => {
    setEscritas((n) => n + 1);
    const resultado = fila.current.then(async () => {
      try { await tarefa(); } finally { setEscritas((n) => n - 1); }
    });
    // A fila nunca pode ficar rejeitada: uma escrita que falhou não pode
    // impedir a seguinte de sequer ser tentada.
    fila.current = resultado.then(() => {}, () => {});
    return resultado;
  }, []);

  const recarregarVenda = useCallback(async () => {
    try {
      const { data } = await getVendaAberta(caixaId);
      aplicarVenda(data || null);
    } catch (error) {
      if (error?.response?.status === 401) { operadorInvalido(); return; }
      // Sem RESPOSTA nenhuma (o tecto de espera, a rede em baixo) não se
      // aprendeu nada — e apagar a conta do ecrã seria afirmar "não há
      // conta", exactamente o género de afirmação sem base que este ficheiro
      // não faz em mais lado nenhum. Pior do que a afirmação é a
      // consequência: com o ecrã vazio, o produto seguinte chama
      // `POST /pos/venda` e o servidor ABRE UMA SEGUNDA conta
      // (`venda.py::abrir_venda` cria sempre uma nova, nunca reaproveita a
      // que está aberta) — a primeira ficava `aberta` para sempre em
      // fat_vendas, que é precisamente a órfã que a regra 2 do cabeçalho
      // existe para evitar. Mantém-se o que está no ecrã, e diz-se que pode
      // estar desactualizado.
      if (semRespostaPos(error)) {
        toast.error('Não foi possível reler a conta — o que está no ecrã pode não estar actualizado.');
        return;
      }
      // O servidor RESPONDEU e recusou: aí sim sabe-se que o ecrã está
      // errado, e ficar sem conta à frente é a única coisa honesta —
      // continuar a mostrar a antiga era manter um estado já sabido falso. O
      // primeiro produto seguinte abre uma nova.
      aplicarVenda(null);
    }
  }, [caixaId, aplicarVenda, operadorInvalido]);

  // O ecrã ficou para trás: a conta foi emitida ou cancelada noutro sítio (ou
  // o turno fechou). Não se insiste — volta-se à conta e relê-se o que existe
  // mesmo.
  const contaFicouParaTras = useCallback(async (error) => {
    toast.error(detalhesErroPos(error, 'Esta conta já não aceita alterações.').mensagem);
    setVista('conta');
    setEmEdicao(null);
    setDocumento(null);
    setErroEmissao(null);
    await recarregarVenda();
  }, [recarregarVenda]);

  // Uma escrita que ficou sem resposta NÃO é uma escrita falhada: pode ter
  // chegado ao servidor e ter sido gravada, com a resposta a perder-se no
  // caminho. Por isso o ecrã não afirma nada sobre a conta — vai relê-la a
  // quem sabe. Sem isto, o pedido morria calado (o único sinal era o
  // spinner de 14px a apagar-se), a operadora tocava outra vez no produto e
  // ficava com ele a dobrar na conta e no papel.
  const semRespostaDoServidor = useCallback(async (error, fallback) => {
    toast.error(
      `${fallback} ${ehTimeoutPos(error)
        ? `O servidor não respondeu em ${SEGUNDOS_DE_ESPERA} segundos.`
        : 'Não houve resposta do servidor.'} A conta foi relida — confirme-a antes de continuar.`
    );
    await recarregarVenda();
  }, [recarregarVenda]);

  const falhou = useCallback((error, fallback) => {
    // Primeiro o "não sei": sem resposta não há status nenhum para ler, e o
    // resto deste caminho só sabe decidir a partir de um status.
    if (semRespostaPos(error)) { semRespostaDoServidor(error, fallback); return; }
    const status = error?.response?.status;
    // 401: o token do operador caducou — o PosApp trata disso, exactamente
    // como o AppInterna já faz no estado da caixa.
    if (status === 401) { operadorInvalido(); return; }
    if (status === 409) { contaFicouParaTras(error); return; }
    toast.error(detalhesErroPos(error, fallback).mensagem);
  }, [operadorInvalido, contaFicouParaTras, semRespostaDoServidor]);

  // Qual das cargas é que ainda interessa. O arranque deixou de ser a única
  // — o ecrã de espera passou a ter um "Tentar novamente" — e sem isto a
  // carga lenta que se pensou perdida ainda chegava depois da nova e escrevia
  // por cima dela: catálogo velho no ecrã, ou pior, a conta como estava há 20
  // segundos. Só a última mandada é que aplica o que traz.
  const cargaDoCatalogo = useRef(0);

  const carregarTudo = useCallback(async () => {
    const carga = cargaDoCatalogo.current + 1;
    cargaDoCatalogo.current = carga;
    const aindaEDaVez = () => cargaDoCatalogo.current === carga;
    setCarregando(true);
    setTentativaDeCarga((n) => n + 1);
    setErro(null);
    try {
      // `getVendaAberta` devolve `null` no início do dia — é o estado normal,
      // não um erro. É também o que devolve a conta em curso depois da tela
      // de descanso, de um F5 ou de o browser ir abaixo, em vez de a
      // operadora repicar tudo.
      const [respCatalogo, respTipos, respVenda] = await Promise.all([
        getCatalogoPos(),
        getTiposPagamentoPos(),
        getVendaAberta(caixaId),
      ]);
      if (!aindaEDaVez()) return;
      setCatalogo({
        categorias: respCatalogo.data?.categorias || [],
        produtos: respCatalogo.data?.produtos || [],
        grupos_personalizacao: respCatalogo.data?.grupos_personalizacao || [],
        // O servidor filtra os produtos cuja categoria está desactivada (não
        // têm separador nenhum onde aparecer) mas CONTA-OS de propósito, para
        // este ecrã poder dizer quantos são e porquê — ver
        // `pos_catalogo.py::_produtos_com_separador`, que existe exactamente
        // para isso. Ler este número é o que fecha a regra 3 do cabeçalho:
        // sem ele, o gestor desactivava "Vendas Aplicações", os 12 artigos
        // dela sumiam do balcão, e a operadora escrevia "uber" na pesquisa e
        // lia "Nenhum produto encontrado" — sem ficar a saber que o artigo
        // existe nem o que pedir a quem o pode repor.
        ocultos: Number(respCatalogo.data?.produtos_ocultos_categoria_inativa) || 0,
      });
      setTiposPagamento(respTipos.data || []);
      aplicarVenda(respVenda.data || null);
    } catch (error) {
      if (!aindaEDaVez()) return;
      if (error?.response?.status === 401) { operadorInvalido(); return; }
      // Sem resposta, a mensagem diz o tecto de espera em vez de um "não foi
      // possível" que não explica nada: o ecrã ficava um spinner eterno e
      // agora, no mínimo, desiste ao fim de um tempo conhecido e diz qual foi.
      setErro(detalhesErroPos(
        error,
        ehTimeoutPos(error)
          ? `O servidor não respondeu em ${SEGUNDOS_DE_ESPERA} segundos — o catálogo desta loja não chegou.`
          : 'Não foi possível carregar o catálogo desta loja.',
      ).mensagem);
    } finally {
      if (aindaEDaVez()) setCarregando(false);
    }
  }, [caixaId, aplicarVenda, operadorInvalido]);

  // Depende só da CAIXA (e de callbacks estáveis do PosApp). Nem da sessão
  // nem do operador: o PosVenda só está montado enquanto há sessão aberta —
  // fechar a caixa devolve o ecrã ao PosCaixaFechada e desmonta isto — e o
  // operador viaja no token. Se este efeito voltasse a correr por causa de um
  // objecto novo vindo de cima, apagava a conta em curso do ecrã com o
  // cliente à frente.
  useEffect(() => { carregarTudo(); }, [carregarTudo]);

  // O relógio do ecrã de espera. Recomeça a cada tentativa e é sempre
  // limpo — um temporizador que sobrevivesse ao fim da carga acendia o aviso
  // por cima de um ecrã que já tinha catálogo à frente.
  useEffect(() => {
    if (!carregando) { setEsperaLonga(false); return undefined; }
    setEsperaLonga(false);
    const relogio = setTimeout(() => setEsperaLonga(true), MS_ATE_AVISAR_ESPERA);
    return () => clearTimeout(relogio);
  }, [carregando, tentativaDeCarga]);

  // Mudar de separador ou escrever na pesquisa recomeça na primeira página —
  // senão ficava-se na página 3 de uma lista que agora tem uma.
  useEffect(() => { setPagina(0); }, [aba, pesquisa]);

  const produtos = catalogo.produtos;
  const gruposPorId = useMemo(
    () => new Map((catalogo.grupos_personalizacao || []).map((g) => [g.id, g])),
    [catalogo.grupos_personalizacao],
  );
  const produtosPorId = useMemo(() => new Map(produtos.map((p) => [p.id, p])), [produtos]);

  // Os grupos do produto, pela ORDEM em que o produto os declara (é a ordem
  // por que a operadora os vai ver e por que os nomes saem no título). Um id
  // que já não venha no catálogo é um grupo desactivado — desaparece daqui, e
  // as escolhas órfãs aparecem como "fora do catálogo" no PosPersonalizacoes.
  const gruposDoProduto = useCallback(
    (produto) => (produto?.grupos_personalizacao || []).map((id) => gruposPorId.get(id)).filter(Boolean),
    [gruposPorId],
  );

  // Não há separador "Sem categoria", e não é esquecimento: foi tirado. A
  // defesa que aqui estava (juntar num separador próprio os produtos cuja
  // categoria não vem no catálogo) NUNCA chegava a disparar —
  // `pos_catalogo.py::_produtos_com_separador` já os filtra do lado do
  // servidor, por isso todo o produto que chega tem, por construção, a
  // categoria na lista que veio na mesma resposta. Um separador que nunca
  // aparece e uma lista que é sempre vazia são piores do que não existirem:
  // quem os lê conta com uma protecção que não há, e o artigo continuava a
  // sumir em silêncio. Quem faz mesmo esse trabalho agora é o aviso do
  // `catalogo.ocultos`, com o número que o servidor manda.
  //
  // E se o servidor um dia deixar de filtrar, nada se perde em silêncio: um
  // produto de categoria desconhecida continua a aparecer no separador
  // "Todos" e continua a ser encontrado pela pesquisa, que varre `produtos`
  // inteiro — fica sem separador próprio, não fica invisível.
  const separadores = useMemo(
    () => [{ id: 'todos', nome: 'Todos' }, ...(catalogo.categorias || [])],
    [catalogo.categorias],
  );

  const termo = semAcentos(pesquisa.trim());
  const visiveis = useMemo(() => {
    // A pesquisa procura em TODAS as categorias, não só na do separador
    // aberto: quem escreve o nome de um artigo quer o artigo, não uma lista
    // vazia porque estava no separador errado. O ecrã diz que é assim.
    if (termo) return produtos.filter((p) => semAcentos(p.nome).includes(termo));
    if (aba === 'todos') return produtos;
    return produtos.filter((p) => p.categoria_id === aba);
  }, [produtos, aba, termo]);

  const totalPaginas = Math.max(1, Math.ceil(visiveis.length / POR_PAGINA));
  const paginaSegura = Math.min(pagina, totalPaginas - 1);
  const daPagina = visiveis.slice(paginaSegura * POR_PAGINA, (paginaSegura + 1) * POR_PAGINA);
  const grelhaVazia = daPagina.length === 0;

  // --- As escritas ------------------------------------------------------------

  // A conta só nasce aqui, ao primeiro produto (regra 2 do cabeçalho). Corre
  // sempre dentro da fila, por isso não precisa de defesa própria contra dois
  // toques ao mesmo tempo: o segundo já encontra `vendaRef.current` cheio.
  const garantirVenda = useCallback(async () => {
    if (vendaRef.current) return vendaRef.current;
    const { data } = await abrirVenda(caixaId);
    aplicarVenda(data);
    return data;
  }, [caixaId, aplicarVenda]);

  const juntarProduto = useCallback((produto, dados) => executar(async () => {
    try {
      const alvo = await garantirVenda();
      const { data } = await juntarLinha(alvo.id, { produto_id: produto.id, ...dados });
      aplicarVenda(data);
      setEmEdicao(null);
    } catch (error) {
      falhou(error, 'Não foi possível juntar o produto à conta.');
    }
  }), [executar, garantirVenda, aplicarVenda, falhou]);

  const tocarProduto = useCallback((produto) => {
    if (produto.vendavel === false) {
      toast.error(
        `${(produto.erros || []).join(' · ') || 'Este produto não pode ser vendido'} — avise o gestor.`
      );
      return;
    }
    // Com uma escolha obrigatória por fazer, abre-se o diálogo em vez de
    // juntar logo (é o que o plano manda). O critério é a MESMA função que o
    // diálogo usa para decidir se abre já no painel dos toppings, e não uma
    // leitura própria do `min_select` — assim nunca há um produto que este
    // ecrã junta directamente e que o diálogo recusaria a seguir.
    if (errosDeSelecao(gruposDoProduto(produto), []).length > 0) {
      setEmEdicao({ produtoId: produto.id, linhaId: null });
      return;
    }
    juntarProduto(produto, { quantidade: 1, opcoes: [] });
  }, [gruposDoProduto, juntarProduto]);

  const gravarLinha = useCallback((produto, linha, dados) => {
    setAGravar(true);
    const terminar = () => setAGravar(false);
    if (linha) {
      executar(async () => {
        try {
          const { data } = await editarLinha(vendaRef.current.id, linha.id, dados);
          aplicarVenda(data);
          setEmEdicao(null);
        } catch (error) {
          falhou(error, 'Não foi possível gravar esta linha.');
        } finally {
          terminar();
        }
      });
      return;
    }
    juntarProduto(produto, dados).then(terminar, terminar);
  }, [executar, aplicarVenda, falhou, juntarProduto]);

  const removerDaConta = useCallback((linha) => executar(async () => {
    try {
      const { data } = await removerLinha(vendaRef.current.id, linha.id);
      aplicarVenda(data);
      setEmEdicao(null);
    } catch (error) {
      falhou(error, 'Não foi possível remover esta linha.');
    }
  }), [executar, aplicarVenda, falhou]);

  const cancelarConta = useCallback(() => executar(async () => {
    // Pode ter deixado de existir entre a confirmação e a vez desta tarefa na
    // fila (a conta foi emitida, ou o 409 de outra escrita já a limpou).
    if (!vendaRef.current) return;
    try {
      await cancelarVenda(vendaRef.current.id);
      // A conta seguinte nasce ao primeiro produto, como sempre — não se
      // abre nenhuma aqui.
      aplicarVenda(null);
      setVista('conta');
      setEmEdicao(null);
      toast.success('Conta cancelada');
    } catch (error) {
      falhou(error, 'Não foi possível cancelar a conta.');
    }
  }), [executar, aplicarVenda, falhou]);

  // O CartaoTotal do PosFinalizar mostra ele próprio a mensagem do servidor
  // quando isto rejeita — por isso só se trata aqui o que muda o ECRÃ (o
  // operador que caducou, a conta que ficou para trás) e relança-se o resto.
  const aplicarDesconto = useCallback((dados) => executar(async () => {
    try {
      const { data } = await aplicarDescontoGlobal(vendaRef.current.id, dados);
      aplicarVenda(data);
    } catch (error) {
      const status = error?.response?.status;
      if (status === 401) { operadorInvalido(); return; }
      if (status === 409) { await contaFicouParaTras(error); return; }
      throw error;
    }
  }), [executar, aplicarVenda, operadorInvalido, contaFicouParaTras]);

  const emitir = useCallback((dados) => {
    if (aEmitir) return;
    setAEmitir(true);
    setErroEmissao(null);
    executar(async () => {
      try {
        const { data } = await finalizarVenda(vendaRef.current.id, dados);
        aplicarVenda(data);
        setDocumento(data.documento || null);
      } catch (error) {
        const status = error?.response?.status;
        if (status === 401) { operadorInvalido(); return; }
        const { mensagem } = detalhesErroPos(error, 'Não foi possível emitir o documento.');
        // Só ESTE 409 é "o ecrã ficou para trás". Os outros que a rota pode
        // dar (o turno já fechado, uma emissão ainda a decorrer) são para
        // mostrar no painel, com a frase do servidor — o de "tente novamente
        // dentro de momentos" precisa que o EMITIR continue lá.
        if (status === 409 && mensagem === MSG_VENDA_NAO_ABERTA) {
          await contaFicouParaTras(error);
          return;
        }
        setErroEmissao({ tipo: tipoDoErroDeEmissao(status, mensagem), mensagem });
      } finally {
        setAEmitir(false);
      }
    });
  }, [aEmitir, executar, aplicarVenda, operadorInvalido, contaFicouParaTras]);

  // A seta de voltar do finalizar E o "Nova Venda" de depois de emitir são o
  // mesmo callback (é o contrato do PosFinalizar). Com um documento emitido,
  // voltar é começar de novo: a conta actual já não existe, e a próxima nasce
  // ao primeiro produto.
  const voltarDoFinalizar = useCallback(() => {
    if (documento) aplicarVenda(null);
    setDocumento(null);
    setErroEmissao(null);
    setVista('conta');
  }, [documento, aplicarVenda]);

  // --- O que está no diálogo do produto ---------------------------------------

  const linhaEmEdicao = emEdicao?.linhaId
    ? (venda?.linhas || []).find((li) => li.id === emEdicao.linhaId) || null
    : null;

  // A linha guarda um RETRATO do produto (nome/preço/IVA de quando entrou na
  // conta). Se o gestor desactivar o artigo com a conta aberta, ele deixa de
  // vir no catálogo — e sem este retrato a operadora não conseguia sequer
  // mudar a quantidade de uma linha que já lá está. O `vendavel: true` não é
  // optimismo: `venda.py::editar_linha` não recorre a `erros_do_produto`
  // (valida a linha pelo retrato), por isso o servidor aceita mesmo esta
  // edição — é o `juntar_linha` de um produto novo que a recusaria.
  const produtoEmEdicao = useMemo(() => {
    if (!emEdicao) return null;
    const doCatalogo = produtosPorId.get(emEdicao.produtoId);
    if (doCatalogo) return doCatalogo;
    if (!linhaEmEdicao) return null;
    return {
      id: linhaEmEdicao.produto_id,
      nome: linhaEmEdicao.produto_nome,
      preco: linhaEmEdicao.produto_preco,
      tax_id: linhaEmEdicao.produto_tax_id,
      foto_url: null,
      grupos_personalizacao: [],
      vendavel: true,
      erros: [],
    };
  }, [emEdicao, produtosPorId, linhaEmEdicao]);

  // A linha foi removida por baixo do diálogo (ou a conta foi recarregada): o
  // diálogo não tem nada para mostrar e fecha-se sozinho.
  useEffect(() => {
    if (emEdicao?.linhaId && !linhaEmEdicao) setEmEdicao(null);
  }, [emEdicao, linhaEmEdicao]);

  // --- Desenho ----------------------------------------------------------------

  // O spinner sozinho era o ecrã de arranque INTEIRO, e sem tecto de espera
  // podia ser o ecrã para sempre: a operadora ficava a olhar para uma roda a
  // girar, sem uma palavra e sem um botão, até se lembrar do F5 — que ninguém
  // lhe disse. Agora o arranque desiste sozinho (o tecto do lib/pos.js), mas
  // 15 s à frente de uma roda muda é tempo a mais com fila; ao fim de
  // MS_ATE_AVISAR_ESPERA o ecrã diz o que está a fazer e põe a saída à vista,
  // sem ainda chamar avaria àquilo — pode estar só a ser lento.
  if (carregando) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-sm text-center flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          {esperaLonga && (
            <>
              <p className="text-muted-foreground">
                O catálogo desta loja está a demorar mais do que o costume a chegar.
              </p>
              <p className="text-sm text-muted-foreground/80">
                Se não chegar em {SEGUNDOS_DE_ESPERA} segundos, o ecrã desiste e avisa. Pode
                tentar já outra vez.
              </p>
              <Button variant="outline" className="h-12 px-6" onClick={carregarTudo}>
                Tentar novamente
              </Button>
            </>
          )}
        </div>
      </div>
    );
  }

  if (erro) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="max-w-sm text-center flex flex-col items-center gap-3">
          <AlertCircle className="h-8 w-8 text-destructive" />
          <p className="text-muted-foreground">{erro}</p>
          {/* Alvo grande: é um PC de balcão com fila à frente, e este é o
              único botão do ecrã inteiro neste estado. */}
          <Button variant="outline" className="h-12 px-6" onClick={carregarTudo}>
            Tentar novamente
          </Button>
        </div>
      </div>
    );
  }

  // `min-h-0` não é decoração e não se pode tirar: um item de flex tem
  // `min-height: auto`, ou seja, nunca encolhe abaixo do próprio conteúdo. Com
  // ele, este bloco fica com a altura que sobra do `min-h-screen` do PosApp
  // menos a barra do PosMenuCaixa, e é essa altura definida que dá scroll
  // próprio à grelha e ao painel da direita (os dois filhos usam `h-full`).
  // Sem ele, a página inteira é que rolava e o TOTAL e o FINALIZAR fugiam
  // para fora do ecrã, que é precisamente onde não podem estar.
  if (vista === 'finalizar') {
    return (
      // O finalizar toma o ecrã TODO, não só o painel da direita: nesse
      // momento não há mais nada a fazer senão receber o dinheiro, a barra do
      // recebido/troco/EMITIR precisa da largura para caber numa linha, e a
      // grelha ao lado só convidaria a picar mais um artigo numa conta que já
      // está a ser paga.
      <div className="flex-1 min-h-0 bg-card">
        <PosFinalizar
          venda={venda}
          tiposPagamento={tiposPagamento}
          aEmitir={aEmitir}
          documento={documento}
          erroEmissao={erroEmissao}
          onVoltar={voltarDoFinalizar}
          onAplicarDesconto={aplicarDesconto}
          onEmitir={emitir}
        />
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
      <section className="flex-1 min-w-0 min-h-0 flex flex-col">
        <div className="shrink-0 border-b bg-card px-3 py-2.5 space-y-2.5">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
            <Input
              value={pesquisa}
              onChange={(e) => setPesquisa(e.target.value)}
              placeholder="Procurar produto…"
              aria-label="Procurar produto"
              className="h-12 pl-11 pr-11 text-base"
            />
            {pesquisa !== '' && (
              <button
                type="button"
                onClick={() => setPesquisa('')}
                aria-label="Limpar a pesquisa"
                className="absolute right-2 top-1/2 -translate-y-1/2 h-9 w-9 rounded-lg flex items-center justify-center hover:bg-accent"
              >
                <X className="h-5 w-5" />
              </button>
            )}
          </div>

          <div className="flex gap-2 overflow-x-auto">
            {separadores.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => { setAba(s.id); setPesquisa(''); }}
                aria-pressed={termo === '' && aba === s.id}
                className={`h-12 px-4 rounded-xl border text-base font-medium whitespace-nowrap shrink-0 transition-colors ${
                  termo === '' && aba === s.id
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-card hover:bg-accent'
                }`}
              >
                {s.nome}
              </button>
            ))}
          </div>

          {termo !== '' && (
            <p className="text-xs text-muted-foreground">
              A procurar em todas as categorias — {visiveis.length}{' '}
              {visiveis.length === 1 ? 'produto' : 'produtos'}.
            </p>
          )}

          {/* Discreto: está à vista enquanto houver artigos escondidos, mas
              em letra pequena e sem cor de alarme — não é uma avaria, é uma
              escolha do gestor. O que não pode é ser invisível.

              Cala-se quando a grelha está vazia, e só nesse caso: aí o mesmo
              aviso já está logo por baixo em destaque, e as duas cópias da
              mesma frase seguidas — uma pequena, uma grande — liam-se como
              dois problemas diferentes. */}
          {!grelhaVazia && <AvisoEscondidos quantos={catalogo.ocultos} />}
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          {grelhaVazia ? (
            <div className="py-16 px-4 flex flex-col items-center gap-4">
              <p className="text-center text-muted-foreground">
                {termo !== ''
                  ? `Nenhum produto encontrado para "${pesquisa.trim()}".`
                  : 'Não há produtos activos neste separador.'}
              </p>
              {/* Em destaque: é aqui, e não noutro sítio qualquer, que ela
                  está mesmo a dar pela falta do artigo. */}
              <AvisoEscondidos quantos={catalogo.ocultos} destaque />
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
              {daPagina.map((produto) => (
                <CartaoProduto key={produto.id} produto={produto} onTocar={tocarProduto} />
              ))}
            </div>
          )}
        </div>

        <Paginacao pagina={paginaSegura} total={totalPaginas} onMudar={setPagina} />
      </section>

      <aside className="w-full lg:w-[26rem] xl:w-[30rem] shrink-0 min-h-0 border-t lg:border-t-0 lg:border-l bg-card flex flex-col">
        {emEdicao && produtoEmEdicao ? (
          <PosDialogoProduto
            produto={produtoEmEdicao}
            grupos={gruposDoProduto(produtoEmEdicao)}
            linha={linhaEmEdicao}
            aGravar={aGravar}
            onGravar={(dados) => gravarLinha(produtoEmEdicao, linhaEmEdicao, dados)}
            onVoltar={() => setEmEdicao(null)}
            onRemover={linhaEmEdicao ? () => removerDaConta(linhaEmEdicao) : undefined}
          />
        ) : (
          <PainelConta
            venda={venda}
            aEscrever={escritas > 0}
            onTocarLinha={(linha) => setEmEdicao({ produtoId: linha.produto_id, linhaId: linha.id })}
            onFinalizar={() => { setErroEmissao(null); setDocumento(null); setVista('finalizar'); }}
            onCancelar={() => setAConfirmarCancelar(true)}
          />
        )}
      </aside>

      <AlertDialog open={aConfirmarCancelar} onOpenChange={setAConfirmarCancelar}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancelar esta conta?</AlertDialogTitle>
            <AlertDialogDescription>
              A conta é deitada fora e não pode ser recuperada. Não é emitida nenhuma fatura
              e não sai dinheiro nenhum da gaveta.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="h-12">Manter a conta</AlertDialogCancel>
            <AlertDialogAction
              className="h-12 bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={cancelarConta}
            >
              Cancelar conta
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
