import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  AlertCircle, Ban, ChevronLeft, ChevronRight, EyeOff, ImageOff, Loader2, MoreHorizontal,
  PauseCircle, Printer, RefreshCw, Search, ShieldAlert, ShoppingCart, Trash2, Undo2, Users, X,
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
import PosPedidoGuiado, { resumoDoPedido } from './PosPedidoGuiado';
import PosReparticao from './PosReparticao';
import useEstadoDaImpressao from './useEstadoDaImpressao';
import {
  getCatalogoPos, getTiposPagamentoPos, getVendaAberta, obterVenda, abrirVenda, juntarLinha,
  editarLinha, removerLinha, aplicarDescontoGlobal, cancelarVenda, finalizarVenda,
  dividirConta, separarConta, contasDaLinha, partesAbertas, ehUmaDasPartes,
  getContasRepartidas, reparticaoDoServidor, unidadesDaConta, CASAS_DA_QUANTIDADE_POS,
  contaTravada, duvidaPorApurar, detalhesErroPos, semRespostaPos,
  ehTimeoutPos, TIMEOUT_PADRAO_MS, entregarContaAoGestor,
  razaoDeNaoComecar, razaoDaGrelhaMorta, MSG_CONTA_TRAVADA_CURTA,
  contaDeOutraCaixa, imprimirPedidoPos,
  razaoDeNaoImprimirPedido as razaoDeNaoImprimirPedidoLib,
  urlDaFotoPos,
  eurosPos as euros,
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

// De quanto em quanto tempo o ecrã volta a PERGUNTAR ao servidor pela conta
// travada. É a peça que faz o ecrã reparar-se sozinho quando o gestor resolve
// a emissão do outro lado — sem isto, a conta destrancada no servidor
// continuava travada no ecrã até alguém se lembrar do F5, que ninguém lhe
// disse (medido: passado mais de um segundo com a reserva já libertada, as
// leituras da conta ficavam em 1 → 1).
//
// 5 s é a escolha, e o custo é o que a justifica: uma leitura por venda
// (`GET /pos/venda/{id}`, um find_one por id mais um por reserva) a cada 5
// segundos, e **só enquanto houver dúvida sobre esta conta** — o relógio
// nasce quando a dúvida aparece e morre quando ela se resolve ou o ecrã se
// desmonta. Um relógio a correr sempre, sobre um balcão que passa o dia
// inteiro sem uma única emissão falhada, seria o oposto disto.
const MS_ENTRE_PERGUNTAS = 5000;
const SEGUNDOS_ENTRE_PERGUNTAS = Math.round(MS_ENTRE_PERGUNTAS / 1000);

// A frase curta do travão, para os sítios onde só cabe uma linha: o `title`
// de um cartão desligado, o toast de um toque que não vai dar a lado nenhum.
// A explicação inteira — o que se passa, o que ela pode fazer AGORA e o que o
// gestor tem de fazer — vive na `FaixaContaTravada`, que fica à vista no
// painel da conta enquanto isto durar.
// A formatação de dinheiro vem de `@/lib/pos` e NÃO é escrita aqui: eram oito
// cópias da mesma linha, e as oito transformavam `undefined`/`null`/`NaN` num
// "€ 0,00" perfeitamente legível. Ver `numeroPos` lá.

// O dinheiro compara-se em CÊNTIMOS INTEIROS, nunca em vírgula flutuante — a
// mesma regra do PosFinalizar, e aqui serve para somar o que falta receber das
// partes de uma conta repartida.
const centimos = (valor) => Math.round((Number(valor) || 0) * 100);

// Porque é que esta conta não se pode repartir — ou `null` quando se pode.
//
// UMA frase, e não duas: é ela que desliga os botões do finalizar com a razão
// à vista por cima deles (`impedeRepartir`) e é ela que o `abrirReparticao`
// diz se alguém lá chegar por outro caminho. Escritas em separado, o botão e a
// recusa acabam a dizer coisas diferentes sobre o mesmo dinheiro por receber.
const razaoDeNaoRepartir = (porCobrar) => {
  if (porCobrar.length === 0) return null;
  const falta = porCobrar.reduce((soma, p) => soma + centimos(p?.totais?.total), 0);
  return `${porCobrar.length === 1
    ? 'Ainda falta cobrar 1 pessoa'
    : `Ainda faltam cobrar ${porCobrar.length} pessoas`} da conta anterior `
    + `(${euros(falta / 100)}). Só há lugar para uma conta repartida de cada vez — `
    + 'cobre-as ou cancele-as primeiro.';
};

// `razaoDeNaoComecar` e `razaoDaGrelhaMorta` mudaram-se para `lib/pos.js` —
// palavra por palavra, como já tinha acontecido com o `ehUmaDasPartes`. A razão
// é a de sempre neste ficheiro: uma decisão enterrada num componente React é
// uma decisão que nenhum teste consegue EXECUTAR, e o guarda que existia sobre
// esta só verificava que certos identificadores apareciam no texto — partir o
// bloqueio a sério deixava-o verde.

// Sem acentos e em minúsculas: ao balcão escreve-se "acai" e o produto
// chama-se "Açaí". Uma pesquisa que só casasse a acentuação exacta era uma
// pesquisa que nunca encontrava nada com pressa em cima.
const semAcentos = (texto) =>
  String(texto || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

// A conta de uma linha já gravada vive no `lib/pos.js` — são DOIS ecrãs a ler
// a mesma linha (este painel e a repartição), e uma segunda cópia daquela
// ordem de arredondamentos era o mesmo artigo a valer dois números diferentes
// em dois sítios do mesmo balcão. Estava aqui escrita à mão e foi de lá que a
// versão do lib nasceu, palavra por palavra.

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
//   409 → 'recusado' **só quando a releitura o confirma**, e 'recusado-incerto'
//     quando não confirma. O servidor RESPONDEU e disse o que aconteceu: a
//     conta foi cancelada a meio, a caixa fechou no outro PC, a conta MUDOU
//     debaixo da emissão (fiscal.py::_MSG_CONTA_ALTERADA_ENTRETANTO), ou já
//     está a decorrer outra emissão. Cada uma dessas frases diz por si se
//     saiu ou não saiu fatura, e por isso o painel mostra-a sem lhe
//     acrescentar afirmação nenhuma por cima. Isto caía no 'incerto', e o
//     defeito não era o texto (a frase do servidor aparecia na mesma): era a
//     MOLDURA a dizer o contrário dela — "não sabemos se a fatura saiu, não
//     volte a emitir, chame o gestor" à volta de uma frase que diz "NÃO saiu
//     nenhuma Fatura Simplificada, confirme a conta como está agora e
//     finalize outra vez", e com o EMITIR desligado, ou seja, impedindo-a de
//     fazer exactamente o que a frase lhe manda fazer.
//
//     Mas o balde 'recusado' escreve, em letras grandes, **"Esta emissão não
//     foi feita."** — e essa é uma afirmação nossa, não do servidor. Para o
//     409 de uma venda JÁ EMITIDA é falsa: a Fatura Simplificada saiu mesmo.
//     Esse 409 costuma ser desviado antes de aqui chegar (a releitura traz o
//     documento e o ecrã mostra-o), mas se a releitura FALHAR — o Wi-Fi a
//     piscar é exactamente o que costuma fazer as duas coisas ao mesmo
//     tempo — caía aqui: título a dizer que não foi feita, nenhum número de
//     fatura no ecrã, e o EMITIR vivo. Medido, e o toque seguinte pedia mesmo
//     uma segunda emissão da mesma venda. Por isso o 'recusado' passou a
//     exigir a PROVA que só a releitura dá (`contaLimpaNoServidor`): conta
//     ainda aberta e sem emissão nenhuma por confirmar. Sem essa prova — a
//     releitura falhou, ou a conta voltou com o travão aceso — o balde é
//     'recusado-incerto': mostra a frase do servidor na mesma, mas por baixo
//     de um título que diz que NÃO SE SABE, e com o EMITIR desligado.
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
//
// E há um caso, um só, em que este 'incerto' é DESPROMOVIDO a 'nada-saiu':
// quando a releitura da venda, feita logo a seguir ao erro (`relida`, o que
// veio do GET /pos/venda/{id}), mostra a conta ainda `aberta` e SEM emissão
// por confirmar. Não é optimismo, é a invariante do servidor: a reserva em
// fat_refs_fiscais nasce ANTES do POST ao Vendus e só desaparece quando o
// servidor SABE que não foi criado documento nenhum
// (`fiscal.py::_libertar_reserva`) — na dúvida ela fica lá, marcada incerta.
// Aberta e sem reserva é o servidor a dizer que não saiu fatura nenhuma, e
// mandar chamar o gestor por causa de um Wi-Fi que piscou é prender o balcão
// inteiro sem razão nenhuma. A despromoção não toca no 503 do
// `VerificacaoFiscalIncerta` (decidido acima, e que deixa mesmo a reserva
// marcada incerta): só apanha o que nunca chegou a vir do servidor — o erro
// sem resposta e o 504 do proxy.
//
// `contaLimpaNoServidor` é essa prova, e é uma só para os dois sítios que a
// usam: o servidor acabou de descrever a conta como ABERTA e sem emissão por
// confirmar. A invariante que lhe dá valor é do servidor, não nossa: a
// reserva em `fat_refs_fiscais` nasce ANTES do POST ao Vendus e só desaparece
// quando ele SABE que não foi criado documento nenhum
// (`fiscal.py::_libertar_reserva`) — na dúvida, fica lá.
const contaLimpaNoServidor = (relida) =>
  !!relida && relida.estado === 'aberta' && !contaTravada(relida);

const tipoDoErroDeEmissao = (status, mensagem, relida) => {
  if (status === 422) return 'dados';
  if (status === 502) return 'vendus';
  if (status === 409) return contaLimpaNoServidor(relida) ? 'recusado' : 'recusado-incerto';
  if (status === 503) return /índice de idempotência/i.test(mensagem) ? 'vendus' : 'incerto';
  if (contaLimpaNoServidor(relida)) return 'nada-saiu';
  return 'incerto';
};

// --- A grelha -----------------------------------------------------------------

function Foto({ url, alt }) {
  const [partida, setPartida] = useState(false);
  // **O endereço resolve-se, não se usa cru.** As fotos vêm de duas origens e
  // com duas formas: a do Vendus é absoluta, a que o dono carregou é relativa
  // (`/api/faturacao/produtos/fotos/…`), e o que não for nenhuma das duas —
  // um `javascript:`, um `//outro-sitio.pt/x.png` — não se desenha de todo.
  // A regra vive em `lib/fotos.js` e é a mesma que o backoffice usa.
  const endereco = urlDaFotoPos(url);
  // Um `foto_url` que já não responde (a imagem foi apagada do servidor)
  // desenhava o ícone de imagem partida do browser dentro do cartão. O
  // onError troca-o pelo mesmo espaço de reserva de quem nunca teve foto.
  if (!endereco || partida) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-muted">
        <ImageOff className="h-7 w-7 text-muted-foreground/50" />
      </div>
    );
  }
  return (
    <img
      src={endereco}
      alt={alt || ''}
      onError={() => setPartida(true)}
      // **A grelha tem dezenas destes mosaicos, num PC de loja.** Sem o
      // `lazy`, abrir o ecrã de venda pede as fotos TODAS de uma vez, as que
      // se veem e as que estao dez ecras abaixo — e o PC do balcao passa
      // esse tempo a nao responder ao dedo. Com ele, o browser pede as que
      // estao a vista e vai buscando o resto a medida que se rola. O
      // `decoding=async` tira a descodificacao do caminho do desenho, que e
      // o outro sitio onde uma foto grande prende o ecra.
      loading="lazy"
      decoding="async"
      className="w-full h-full object-cover"
    />
  );
}

function CartaoProduto({ produto, onTocar, bloqueio }) {
  // `vendavel: false` vem do servidor (`pos_catalogo.py`, que corre o mesmo
  // `precos.erros_do_produto` que a venda usa para recusar a linha com 422).
  // O cartão fica morto e com a razão escrita — "Sem IVA definido" é
  // precisamente a frase que a operadora repete a quem o pode corrigir.
  const vendavel = produto.vendavel !== false;

  // `bloqueio` é a frase que explica porque é que ESTE toque não vai dar a lado
  // nenhum — ou `null` quando dá. São duas razões e as duas vêm do servidor:
  //
  // · a conta está travada por uma emissão por confirmar, e o servidor recusa a
  //   linha com 409 (`venda.py::_garante_sem_emissao`);
  // · há partes por cobrar de uma conta repartida, e o servidor recusa ABRIR a
  //   conta seguinte com 409 (`venda.py::abrir_venda`).
  //
  // Nos dois casos o ecrã não pode CONVIDAR ao toque — descobri-lo assim é
  // descobri-lo com o cliente à frente. O cartão fica apagado, e nunca com a
  // moldura tracejada do "não pode ser vendido": o artigo não tem defeito
  // nenhum — quem não aceita é a conta, e quem o explica é a faixa do painel ao
  // lado.
  const aparencia = !vendavel
    ? 'border-dashed opacity-70 cursor-not-allowed'
    : bloqueio
      ? 'opacity-50 cursor-not-allowed'
      : 'hover:border-primary hover:shadow-md active:scale-[0.97]';

  return (
    <button
      type="button"
      onClick={() => onTocar(produto)}
      disabled={!vendavel || !!bloqueio}
      title={bloqueio || (vendavel ? produto.nome : (produto.erros || []).join(' · '))}
      className={`text-left rounded-2xl border bg-card overflow-hidden flex flex-col transition-all ${aparencia}`}
    >
      {/* 4:3 e não quadrada: a foto quadrada fazia cada mosaico crescer com a
          largura da coluna e o ecrã inteiro parecia esticado. Menos alta, cabe
          mais artigo sem obrigar a rolar — que é o que a operadora faz mais. */}
      <div className="aspect-[4/3] w-full overflow-hidden">
        <Foto url={produto.foto_url} alt={produto.nome} />
      </div>
      <div className="p-2 flex-1 flex flex-col gap-0.5">
        <span className="text-sm font-medium leading-tight line-clamp-2">{produto.nome}</span>
        {vendavel ? (
          <span className="font-heading font-bold text-base tabular-nums mt-auto">
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

// A conta está TRAVADA. São duas maneiras de lá chegar, e a faixa distingue-as
// porque o que se SABE é diferente em cada uma:
//
// · `peloServidor` — o servidor diz que esta venda tem uma reserva fiscal e
//   ainda não está emitida (`venda.emissao_por_confirmar`): pode haver uma
//   Fatura Simplificada real a nascer, ou já nascida e por confirmar.
// · a outra — a emissão falhou e a releitura da venda também
//   (`duvidaPorApurar`): não se sabe sequer se há reserva. É menos do que
//   saber, nunca mais, e por isso trava exactamente da mesma maneira.
//
// Esta faixa vive no painel da CONTA, e não só dentro do finalizar, porque é
// para aqui que a seta de voltar leva. Era esse metade do defeito: o painel
// do finalizar dizia "não sabemos se a fatura saiu", a operadora voltava
// atrás — e encontrava uma conta com ar perfeitamente normal, editável e com
// o FINALIZAR aceso, sem uma palavra sobre o que estava a acontecer.
//
// **É a ÚNICA conta que pode sair da frente sem estar resolvida, e é por isso
// que ela é uma excepção escrita e não uma porta.** A regra do balcão é uma
// conta de cada vez — `venda.py::abrir_venda` responde 409 a quem tentar
// começar a do cliente seguinte com uma conta por resolver neste posto. Uma
// conta travada é o caso em que essa regra pararia o balcão sem remédio: a
// operadora não a consegue cobrar nem cancelar (as cinco rotas de escrita
// recusam-na, `venda.py::_garante_sem_emissao`), e quem a resolve é o gestor,
// no backoffice. Por isso a rota não a conta como conta por resolver — e
// nenhuma outra.
//
// Diz QUATRO coisas, e as duas do meio são as que faltavam — a faixa antiga
// dizia só a primeira, e era por isso que a conta travada era um beco sem
// saída que levava o posto inteiro atrás:
//
//   1. o que se passa e o que a conta deixou de aceitar;
//   2. **o que ela pode fazer agora**: ENTREGAR esta conta ao gestor
//      (`POST /pos/venda/{id}/entregar-ao-gestor`) e servir o cliente seguinte.
//      O servidor grava a marca, e só aceita entregar esta: uma conta normal
//      acaba aqui, cobrada ou cancelada. Era aqui que estava a raiz do pior
//      defeito desta ronda — o botão não falava com o servidor, e a "excepção"
//      de `abrir_venda` era deduzida da reserva fiscal em vez de gravada;
//   3. o que o gestor tem de fazer, e a consequência que ela vai encontrar
//      logo à noite se ninguém o fizer: o fecho da caixa recusa-se enquanto
//      houver uma conta assim (`caixa.py::_venda_com_emissao_viva`);
//   4. que o ecrã se destranca SOZINHO — não há F5 nenhum a adivinhar.
//
// Nunca um "tente novamente" na emissão: é precisamente o que não se pode
// fazer sem saber se a fatura saiu.
function FaixaContaTravada({ peloServidor, aPerguntar, onPerguntar, onLargar }) {
  return (
    <div className="shrink-0 border-b-2 border-destructive bg-destructive/10 px-4 py-3 space-y-2.5">
      <div className="flex items-start gap-2.5">
        <ShieldAlert className="h-6 w-6 text-destructive shrink-0" />
        <div className="min-w-0 text-sm">
          <p className="font-heading font-bold text-base">
            {peloServidor
              ? 'Conta travada: emissão por confirmar.'
              : 'Conta travada: não sabemos se a fatura saiu.'}
          </p>
          {peloServidor ? (
            <p className="mt-1">
              Esta conta tem uma emissão de Fatura Simplificada em curso ou por confirmar. Não
              aceita produtos novos, alterações, descontos nem cancelamento, e não pode voltar a ser
              emitida aqui.
            </p>
          ) : (
            <p className="mt-1">
              Uma emissão desta conta falhou e não foi possível voltar a lê-la no servidor para
              saber se a Fatura Simplificada chegou a sair. Até isso se saber, a conta fica como
              está: não aceita produtos novos, alterações, descontos nem cancelamento, e não volta a
              ser emitida aqui.
            </p>
          )}
          <p className="mt-1">
            <strong>Não fique à espera:</strong> entregue esta conta ao gestor e sirva o cliente
            seguinte. Ela fica guardada no servidor tal como está, marcada como dele, e passa a
            aparecer na lista do backoffice — não volta a este ecrã, nem depois de ele libertar a
            reserva.
          </p>
          <p className="mt-1">
            <strong>Chame o gestor.</strong> Só depois de se ver no Vendus se a fatura chegou a sair
            é que se sabe o que fazer a esta conta
            {peloServidor ? ' — e o fecho desta caixa fica bloqueado enquanto ela estiver assim' : ''}.
          </p>
          <p className="mt-1 text-muted-foreground">
            O ecrã volta a perguntar ao servidor de {SEGUNDOS_ENTRE_PERGUNTAS} em{' '}
            {SEGUNDOS_ENTRE_PERGUNTAS} segundos e destranca-se sozinho assim que o gestor resolver.
            Não é preciso recarregar a página.
          </p>
        </div>
      </div>

      {/* Os dois alvos grandes, empilhados: é um PC de balcão com fila à
          frente, e a largura deste painel não chega para os pôr lado a lado
          sem lhes cortar o texto. */}
      <div className="flex flex-col gap-2">
        <Button variant="outline" className="h-12 w-full" onClick={onPerguntar} disabled={aPerguntar}>
          {aPerguntar ? (
            <Loader2 className="h-5 w-5 mr-2 animate-spin" />
          ) : (
            <RefreshCw className="h-5 w-5 mr-2" />
          )}
          {aPerguntar ? 'A perguntar ao servidor…' : 'Já foi resolvida?'}
        </Button>
        <Button className="h-12 w-full" onClick={onLargar}>
          <PauseCircle className="h-5 w-5 mr-2" />
          Servir o cliente seguinte
        </Button>
      </div>
    </div>
  );
}

// A conta TRAVADA que ela largou para servir o cliente seguinte. Não desaparece
// do ecrã em silêncio (regra 3 do cabeçalho): continua a existir no servidor, e
// é por isso que o id está aqui à vista e em texto seleccionável.
//
// **Não tem botão de retomar, e é isso que ela é.** Retomar não é coisa que a
// operadora consiga fazer com esta conta: travada, ela não aceita produtos,
// alterações, descontos, cancelamento nem emissão — trazê-la de volta para a
// frente só lhe tirava o lugar da conta do cliente que está ali agora. Quem a
// resolve é o gestor, na lista de contas por cobrar do backoffice
// (`FatReservasPresas.js`), com o documento à vista no Vendus. O que esta nota
// tem de dar é a referência, para ele a encontrar.
//
// **Esta nota vive só nesta montagem do ecrã, e agora isso está certo.** Um F5
// leva-a, e não se perde nada com isso: quem guarda esta conta é o SERVIDOR, que
// lhe gravou a marca `entregue_ao_gestor_em` no momento em que ela foi entregue
// (`venda.py::entregar_ao_gestor`). A nota é o recibo do instante — a referência
// à mão, com o cliente à frente — e não o registo.
//
// Enquanto a entrega foi um gesto só do browser, esta nota ERA o único registo
// dela, e um F5 apagava-o. Pior: o comentário que aqui estava prometia que o
// fecho da caixa «se recusa a fechar enquanto a emissão dela estiver viva» —
// e o `libertar` do gestor é exactamente o que mata essa emissão. Depois disso
// não sobrava sítio nenhum onde a conta aparecesse.
//
// Onde ela está agora, e é o que a nota diz por extenso:
//   - na lista do gestor (`GET /caixa/contas-esquecidas`), mesmo com este turno
//     ainda a decorrer — que é a lista onde ele a resolve;
//   - no fecho desta caixa, que conta TODAS as contas abertas da sessão e as
//     mostra antes do Z (`caixa.py::_contas_abertas_da_sessao`), marcada como
//     do gestor;
//   - a travar o fecho enquanto a emissão dela estiver viva
//     (`caixa.py::_venda_com_emissao_viva`) — e só enquanto estiver.
function AvisoContaTravadaLargada({ conta }) {
  return (
    <div className="shrink-0 border-b bg-muted/40 px-4 py-3 flex items-start gap-2.5">
      <PauseCircle className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">
          Conta travada entregue ao gestor
          {conta.total != null ? `: ${euros(conta.total)}` : ''}.
        </p>
        {/* A nota diz o que se SABE desta conta, e o que se sabe depende de
            como ela ficou travada — a bandeira do servidor é uma certeza, a
            releitura falhada não é nenhuma. Escrever "tem uma emissão por
            confirmar" por cima da segunda era afirmar o que ninguém viu. */}
        <p className="text-muted-foreground mt-1">
          {conta.peloServidor
            ? 'Está guardada no servidor, com a emissão por confirmar, e já aparece na lista do gestor no backoffice — mesmo com este turno a decorrer. Não volta a este ecrã. O fecho desta caixa vai recusar-se enquanto a emissão dela estiver viva.'
            : 'Está guardada no servidor com uma emissão por apurar: não se sabe se a Fatura Simplificada chegou a sair. Já aparece na lista do gestor no backoffice, e é ele que o confirma. Não volta a este ecrã. Se tiver mesmo ficado presa, o fecho desta caixa vai recusar-se enquanto ela estiver assim.'}
          {' '}Dê-lhe esta referência:
        </p>
        <p className="font-mono text-xs break-all select-all mt-1">{conta.id}</p>
      </div>
    </div>
  );
}

// A conta foi repartida e ficaram partes por cobrar — e a operadora está no
// balcão, não no ecrã das partes. Sem esta nota, sair do ecrã da repartição
// para servir o cliente seguinte fazia as partes desaparecerem de vista: o
// dinheiro por receber continuava a existir (as vendas ficam `aberta` no
// servidor) mas não havia no ecrã uma única palavra sobre ele nem caminho de
// volta. É a mesma regra do `AvisoContaTravadaLargada` logo acima — nada
// desaparece do ecrã em silêncio.
function AvisoPartesPorCobrar({ porCobrar, deQuantas, faltaCentimos, onVoltar }) {
  return (
    <div className="shrink-0 border-b-2 border-primary bg-primary/10 px-4 py-3 flex items-start gap-2.5">
      <Users className="h-5 w-5 text-primary shrink-0 mt-0.5" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">
          {porCobrar === 1
            ? `Falta cobrar 1 pessoa de ${deQuantas}`
            : `Faltam cobrar ${porCobrar} pessoas de ${deQuantas}`}
          {' — '}
          <span className="tabular-nums font-semibold">{euros(faltaCentimos / 100)}</span>.
        </p>
        {/* Esta frase é uma PROMESSA sobre dinheiro, e durante um tempo foi
            falsa: o Z lia só as vendas `emitida` e o único travão do fecho
            exigia uma reserva fiscal, que uma parte que nunca foi ao EMITIR
            não tem — a caixa fechava e o Z saía sem uma palavra sobre elas.
            Agora conta mesmo: `caixa.py::_contas_abertas_da_sessao` soma
            TODAS as contas abertas da sessão, o diálogo do fecho mostra-as
            antes da contagem e o Z leva-as escritas. */}
        <p className="text-muted-foreground mt-1">
          Cada uma leva a sua fatura. Enquanto não forem cobradas ou canceladas, ficam abertas no
          servidor, e o fecho desta caixa mostra-as antes de assinar o Z.
        </p>
        <Button className="h-12 w-full mt-2" onClick={onVoltar}>
          Voltar às partes
        </Button>
      </div>
    </div>
  );
}

function LinhaDaConta({ linha, onTocar, onRemover, travada }) {
  const { unitario, total, desconto } = contasDaLinha(linha);
  // O pedido em duas frases: o serviço e o nome numa (`Levar · Maria`), as
  // escolhas com as doses noutra (`Nutella 2× · Leite condensado 1×`). É o que
  // a operadora confere com o cliente antes de finalizar, e é lido pela MESMA
  // regra do papel da cozinha (`talao.pedido_da_cozinha`) — o ecrã e o papel
  // nunca dizem a mesma linha por ordens diferentes.
  const { servico, escolhas } = resumoDoPedido(linha);

  // Travada, a linha continua a LER-SE exactamente como está (é a conta que o
  // gestor vai ter de olhar, e apagá-la não ajudava ninguém) — o que
  // desaparece é o convite ao toque: sem realce, sem o afundar, e sem abrir o
  // diálogo de edição.
  // DUAS zonas, e não um botão só: o corpo abre o diálogo do produto (como
  // sempre abriu) e o X à direita tira a linha da conta num toque. Um botão
  // dentro de outro botão não é HTML válido — o X ficava sem clique próprio e
  // o toque nele abria o diálogo — por isso a linha passa a ser uma grelha com
  // o corpo a ocupar as três primeiras colunas.
  //
  // O X apaga SEM perguntar, de propósito: é o que o «Remover da conta» do
  // diálogo já fazia (PosDialogoProduto), e o pedido do dono foi precisamente
  // poupar os dois toques do desvio. Apaga a LINHA inteira — para tirar uma
  // unidade de três continua a ser pelo diálogo, onde está a quantidade.
  return (
    <div
      className={`grid grid-cols-[1fr_2.5rem_6rem_2.75rem] gap-2 items-stretch px-4 border-b ${
        travada ? '' : 'hover:bg-accent'
      }`}
    >
      <button
        type="button"
        onClick={() => onTocar(linha)}
        disabled={travada}
        title={travada ? MSG_CONTA_TRAVADA_CURTA : undefined}
        className={`col-span-3 text-left grid grid-cols-[1fr_2.5rem_6rem] gap-2 items-start py-3 ${
          travada ? 'cursor-default' : 'active:scale-[0.99] transition-transform'
        }`}
      >
        <div className="min-w-0">
          <p className="font-medium leading-tight">{linha.produto_nome}</p>
          {servico && <p className="text-xs text-muted-foreground leading-snug mt-0.5">{servico}</p>}
          {escolhas && <p className="text-xs text-muted-foreground leading-snug mt-0.5">{escolhas}</p>}
          <p className="text-xs text-muted-foreground mt-0.5 tabular-nums">
            {euros(unitario)} cada
            {desconto > 0 && ` · desconto ${euros(desconto)}`}
          </p>
        </div>
        <span className="font-heading font-bold text-lg tabular-nums text-center">{linha.quantidade}</span>
        <span className="font-heading font-bold text-lg tabular-nums text-right">{euros(total)}</span>
      </button>

      {/* Travada, o X DESAPARECE — a linha continua a ler-se, que é o que o
          gestor vai ter de olhar, mas já não se toca. O servidor recusaria na
          mesma (`remover_linha` passa pelo `_garante_sem_emissao`), e um botão
          que existe para dar erro é pior do que botão nenhum. */}
      {travada ? <span aria-hidden="true" /> : (
        <button
          type="button"
          onClick={() => onRemover(linha)}
          title="Remover da conta"
          aria-label={`Remover ${linha.produto_nome} da conta`}
          className="my-2 flex items-center justify-center rounded-md text-destructive/70 hover:bg-destructive/10 hover:text-destructive active:scale-95 transition"
        >
          <X className="h-5 w-5" />
        </button>
      )}
    </div>
  );
}

function PainelConta({
  venda, caixa, aEscrever, travada, travadaPeloServidor, contasTravadasLargadas, aPerguntar,
  partesPorCobrar,
  onPerguntar, onLargar, onVoltarAsPartes, onTocarLinha, onRemoverLinha,
  onFinalizar, onCancelar,
  razaoDeNaoImprimirPedido, onImprimirPedido, aImprimirPedido,
}) {
  const linhas = venda?.linhas || [];
  const totais = venda?.totais || {};
  // "N Produtos" e "N Uni." são coisas diferentes e no print aparecem as
  // duas: produtos são LINHAS da conta, unidades é a soma das quantidades.
  //
  // A soma vive em `lib/pos.js` e é feita em unidades INTEIRAS: somada em
  // vírgula flutuante, uma parte recuperada de uma conta dividida escrevia
  // aqui "0.9666699999999999 Uni.". E escreve-se com o separador decimal de
  // cá — o `unidades` cru saía com um ponto no meio de um ecrã em português.
  const unidades = unidadesDaConta(linhas)
    .toLocaleString('pt-PT', { maximumFractionDigits: CASAS_DA_QUANTIDADE_POS });

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      {/* Em cima de tudo, antes da conta: é a primeira coisa a ler quando se
          volta do finalizar, e a única que explica todos os botões mortos
          que vêm a seguir. */}
      {travada && (
        <FaixaContaTravada
          peloServidor={travadaPeloServidor}
          aPerguntar={aPerguntar}
          onPerguntar={onPerguntar}
          onLargar={onLargar}
        />
      )}

      {/* As contas travadas já largadas. Ficam por baixo da faixa — nas raras
          vezes em que as duas aparecem juntas (a largada voltou a ser a conta
          em curso porque o arranque a foi buscar outra vez), a que está À
          FRENTE dela é que manda.
          UMA NOTA POR CONTA, e não um único lugar: uma segunda emissão falhada
          no mesmo turno apagava a nota da primeira do ecrã — a mesma
          desaparição silenciosa que estas notas existem para impedir, e logo
          sobre a conta que o gestor precisa de encontrar. */}
      {contasTravadasLargadas.map((conta) => (
        <AvisoContaTravadaLargada key={conta.id} conta={conta} />
      ))}

      {partesPorCobrar && (
        <AvisoPartesPorCobrar
          porCobrar={partesPorCobrar.porCobrar}
          deQuantas={partesPorCobrar.deQuantas}
          faltaCentimos={partesPorCobrar.faltaCentimos}
          onVoltar={onVoltarAsPartes}
        />
      )}

      {/* **Esta conta veio de OUTRA caixa deste PC.** Não é um erro nem um
          aviso: é a troca de caixa, e é o caminho normal quando o localStorage
          não traz caixa e o ecrã «Qual caixa?» do PosApp pede uma. O que era
          um BECO — a rota recusava a conta seguinte por causa dela e nenhum
          ecrã a mostrava — passou a ser isto: a conta está à frente e diz de
          onde vem. Sem esta linha, a operadora olha para uma conta que não
          reconhece com o cliente à frente.
          A caixa da CONTA é que manda no que lhe acontece: cobrá-la emite no
          turno em que ela nasceu, e é nesse Z que ela entra. */}
      {contaDeOutraCaixa(venda, caixa?.id) && (
        <div className="shrink-0 border-b bg-muted/40 px-4 py-3 flex items-start gap-2.5">
          <ShoppingCart className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1 text-sm">
            <p className="font-medium">Esta conta ficou aberta noutra caixa deste PC.</p>
            <p className="text-muted-foreground mt-1">
              Está à sua frente e acaba-se aqui — cobre-a ou cancele-a antes de começar a do
              cliente seguinte. Quando a cobrar, ela entra no fecho da caixa em que foi aberta,
              e não no da caixa «{caixa?.nome || '—'}».
            </p>
          </div>
        </div>
      )}

      {/* Esta conta é uma PARTE de uma conta repartida — é o que se vê depois
          de um F5 a meio da cobrança, quando o `GET /pos/venda/aberta` devolve
          a parte mais recente e o ecrã já não tem a lista das outras. Sem esta
          nota, a parte apresenta-se como uma venda normal e a operadora cobra
          3,00 € a quem devia 8,99 €. Não se reconstrói a lista (não há rota
          que a peça), mas diz-se o que se sabe: esta conta faz parte de uma
          conta maior, e a referência da mãe fica à vista para o gestor. */}
      {venda?.conta_mae_id && !partesPorCobrar && (
        <div className="shrink-0 border-b bg-muted/40 px-4 py-3 flex items-start gap-2.5">
          <Users className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1 text-sm">
            <p className="font-medium">Esta conta é a parte de uma pessoa.</p>
            <p className="text-muted-foreground mt-1">
              Nasceu de uma conta repartida e leva a sua própria fatura — não é a conta toda. As
              outras partes continuam abertas no servidor. Referência da conta de origem:
            </p>
            <p className="font-mono text-xs break-all select-all mt-1">{venda.conta_mae_id}</p>
          </div>
        </div>
      )}

      <div className="shrink-0 grid grid-cols-[1fr_2.5rem_6rem_2.75rem] gap-2 px-4 h-11 items-center border-b text-xs uppercase tracking-wide text-muted-foreground">
        <span className="flex items-center gap-2">
          Produto
          {aEscrever && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
        </span>
        <span className="text-center">Qtd</span>
        <span className="text-right">Preço</span>
        {/* A coluna do X. Vazia no cabeçalho, mas TEM de existir: sem ela o
            "Preço" alinhava-se por três colunas e as linhas por quatro. */}
        <span aria-hidden="true" />
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
            <LinhaDaConta
              key={linha.id} linha={linha} travada={travada}
              onTocar={onTocarLinha} onRemover={onRemoverLinha}
            />
          ))
        )}
      </div>

      <div className="shrink-0 px-3 pt-3">
        {/* **A ficha da cozinha, ANTES de a conta ser finalizada** — é o que a
            operadora usa quando o cliente pede para começarem a fazer o copo
            enquanto ele decide o resto.

            Desligado quando não há programa de impressão a ouvir na loja, e a
            dizer porquê: um "Imprimir" que não imprime nada fazia a operadora
            carregar três vezes e dar o cliente por servido sem pedido nenhum
            na cozinha. E desligado numa conta ainda VAZIA, que era papel em
            branco a sair. A decisão está em `razaoDeNaoImprimirPedido`
            (lib/pos.js), e não aqui, porque uma condição dentro de um botão
            não se corre em teste nenhum. */}
        <Button
          variant="outline"
          className="w-full h-12 justify-start"
          onClick={onImprimirPedido}
          disabled={!venda || !!razaoDeNaoImprimirPedido}
        >
          {aImprimirPedido
            ? <Loader2 className="h-5 w-5 mr-2 animate-spin" />
            : <Printer className="h-5 w-5 mr-2" />}
          Imprimir Pedido
        </Button>
        <p className="text-[11px] text-muted-foreground leading-snug mt-1.5">
          {razaoDeNaoImprimirPedido
            || (!venda
              ? 'Não há conta nenhuma à frente para mandar à cozinha.'
              : 'Manda a ficha desta conta para a impressora da cozinha, sem a '
                + 'finalizar. É por aqui que a cozinha recebe o pedido: '
                + 'finalizar a conta manda o talão ao cliente e mais nada.')}
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
              disabled={!venda || travada}
              className="text-destructive focus:text-destructive"
            >
              <Trash2 className="h-4 w-4 mr-2" /> Cancelar conta
              {!venda && (
                <span className="ml-auto text-[10px] text-muted-foreground">Sem conta aberta</span>
              )}
              {/* A razão à vista, a mesma regra do "Sem conta aberta" ao lado.
                  E é a pior de todas para se descobrir com um clique mudo:
                  cancelar uma conta com emissão por confirmar é exactamente o
                  que faria desaparecer a última venda ligada a uma Fatura
                  Simplificada que pode ter saído — o servidor recusa-o
                  (venda.py::cancelar_venda), e o ecrã não o oferece. */}
              {venda && travada && (
                <span className="ml-auto text-[10px] text-muted-foreground">
                  {travadaPeloServidor ? 'Emissão por confirmar' : 'Emissão por apurar'}
                </span>
              )}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Travada, o FINALIZAR também morre: do outro lado o EMITIR estaria
            desligado na mesma (é a mesma conta e o mesmo travão), e mandar a
            operadora ao ecrã de pagamento para lá encontrar tudo cinzento era
            fazê-la percorrer o caminho todo para descobrir a mesma coisa que
            a faixa já lhe diz aqui. */}
        <Button
          className="h-16 text-lg font-heading font-bold"
          disabled={linhas.length === 0 || travada}
          onClick={onFinalizar}
        >
          FINALIZAR
        </Button>
      </div>
    </div>
  );
}

// --- O ecrã -------------------------------------------------------------------

export default function PosVenda({ caixa, onOperadorInvalido, contasCopiadas }) {
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
  // A zona que rola, para a poder pôr no topo quando a lista por baixo muda.
  const grelhaRef = useRef(null);

  // 'conta' | 'produto' | 'finalizar'. O diálogo do produto substitui o
  // PAINEL DIREITO (é o que o print manda); o finalizar toma o ecrã inteiro —
  // nesse momento não há mais nada a fazer senão receber o dinheiro, e a
  // barra do recebido/troco/EMITIR precisa da largura toda para caber numa
  // linha só.
  const [vista, setVista] = useState('conta');
  const [emEdicao, setEmEdicao] = useState(null); // { produtoId, linhaId | null }
  // O pedido guiado é um pop-up POR CIMA de tudo, e não uma vista — guarda o
  // produto e os grupos que lhe deram origem, não ids: os grupos vêm do
  // catálogo, que é lido uma vez por caixa, e a conversa que já está aberta
  // não pode mudar de passos a meio se alguma coisa o recarregar.
  const [pedidoGuiado, setPedidoGuiado] = useState(null); // { produto, grupos, linha | null }
  const [aGravar, setAGravar] = useState(false);

  const [aEmitir, setAEmitir] = useState(false);
  // A emissão já respondeu (mal) e o que corre AGORA é a pergunta ao servidor
  // sobre o que aconteceu àquela venda (`apurarAEmissao`). São duas esperas
  // com tectos muito diferentes — 90 s a emitir, 15 s a perguntar — e o botão
  // dizia "A emitir…" durante as duas: até 105 segundos, e nos últimos 15
  // não estava a emitir coisa nenhuma. Quem lê isso vê uma emissão que não
  // acaba, e uma emissão que não acaba é o que faz mexer no que não se deve.
  const [aConfirmar, setAConfirmar] = useState(false);
  const [documento, setDocumento] = useState(null);
  // O documento não chegou pela resposta do EMITIR: o ecrã foi lê-lo depois
  // de a emissão ter falhado à frente da operadora (ver `apurarAEmissao`).
  const [documentoRecuperado, setDocumentoRecuperado] = useState(false);
  const [erroEmissao, setErroEmissao] = useState(null);
  const [aConfirmarCancelar, setAConfirmarCancelar] = useState(false);
  const [aImprimirPedido, setAImprimirPedido] = useState(false);
  // Ver a nota igual no PosMenuCaixa: cada ecrã pergunta o seu.
  const { estado: estadoImpressao, recarregar: recarregarImpressao } =
    useEstadoDaImpressao();
  const razaoDeNaoImprimirPedido = razaoDeNaoImprimirPedidoLib({
    venda, estado: estadoImpressao, aImprimir: aImprimirPedido,
  });

  // **A ficha da cozinha, sem finalizar a conta.** Põe o trabalho na fila do
  // servidor — não diz "impresso", que é uma afirmação sobre uma impressora
  // que este ecrã não vê. Quem imprime é o programa da loja.
  //
  // Não trava a conta nem toca em dinheiro nenhum: é papel. Duas vezes no
  // botão são duas fichas, de propósito (o servidor usa chave nova de cada
  // vez) — a ficha caiu, molhou-se, a cozinha perdeu-a.
  const imprimirPedido = useCallback(async () => {
    if (!venda || aImprimirPedido) return;
    setAImprimirPedido(true);
    try {
      await imprimirPedidoPos(venda.id);
      toast.success('Pedido na fila da impressora da cozinha.');
    } catch (error) {
      const { mensagem } = detalhesErroPos(
        error, 'Não foi possível mandar este pedido para a cozinha.');
      toast.error(mensagem);
    } finally {
      setAImprimirPedido(false);
      recarregarImpressao();
    }
  }, [venda, aImprimirPedido, recarregarImpressao]);

  // As contas TRAVADAS que ela largou para servir o cliente seguinte —
  // `[{ id, total, peloServidor }]`, o mínimo para a nota do painel poder dizer
  // QUAL é cada uma e dar ao gestor a referência. Não é a conta inteira de
  // propósito: a conta inteira, guardada aqui, era uma segunda cópia do que só
  // o servidor sabe, e ficaria velha no instante seguinte.
  //
  // Só entram aqui contas travadas: uma conta NORMAL não sai da frente sem
  // estar cobrada ou cancelada, porque `venda.py::abrir_venda` recusa abrir a
  // seguinte por cima dela.
  //
  // **Uma LISTA, e não uma conta só.** Duas emissões falhadas no mesmo turno
  // são duas contas para o gestor ir buscar, e a segunda apagava a nota da
  // primeira do ecrã.
  const [contasTravadasLargadas, setContasTravadasLargadas] = useState([]);
  // Há uma pergunta ao servidor a decorrer (o botão da faixa, ou o relógio).
  const [aPerguntar, setAPerguntar] = useState(false);

  // A conta que está a ser repartida, e as partes que dela nasceram:
  // `{ modo, mae, partes }` — `partes` a `null` enquanto a repartição ainda
  // não foi feita.
  //
  // **Vive aqui, e não dentro do `PosReparticao`.** Esse ecrã DESMONTA-SE de
  // cada vez que se vai cobrar uma parte (o finalizar toma o ecrã todo), e o
  // que morria com ele era exactamente a lista do que falta receber — com
  // duas pessoas por cobrar e nenhuma forma de voltar a elas.
  //
  // Não sobrevive a um F5, e é uma decisão: as partes são vendas normais e
  // ficam guardadas no servidor, mas não há rota que peça "as partes desta
  // mãe". Depois de um F5 o `GET /pos/venda/aberta` devolve UMA delas, e o
  // painel da conta diz o que ela é (`conta_mae_id`) em vez de a mostrar como
  // se fosse a conta inteira.
  const [reparticao, setReparticao] = useState(null);
  // A repartição está a ser pedida ao servidor (o botão do ecrã).
  const [aRepartir, setARepartir] = useState(false);
  // O id da parte que está a ser cancelada, ou `null`.
  const [aCancelarParte, setACancelarParte] = useState(null);

  // A conta também vive numa ref: `garantirVenda` corre dentro da fila de
  // escritas (abaixo) e precisa de saber se JÁ existe uma venda neste
  // instante — o `venda` do state é o de quando a função foi criada, e com
  // ele dois toques seguidos abriam duas contas.
  const vendaRef = useRef(null);

  // A lista das partes tem de ouvir o servidor pela MESMA porta por onde a
  // conta em frente o ouve. Quando a venda que o servidor acabou de descrever
  // é uma das partes em cobrança — emitida, cancelada, relida depois de uma
  // emissão que correu mal —, a pastilha dela na lista muda com ela. Sem isto,
  // a parte ficava eternamente "por cobrar" no ecrã depois de a fatura ter
  // saído, e o *Falta Receber* não descia.
  //
  // `{ ...antiga, ...nova }` e não a nova pura: `_venda_publica` não traz o
  // `documento` (só o `finalizar` e o `GET /pos/venda/{id}` o trazem), e uma
  // resposta sem ele não pode apagar o número de fatura que já lá estava.
  const sincronizarParte = useCallback((atualizada) => {
    setReparticao((r) => (
      r?.partes && r.partes.some((p) => p.id === atualizada.id)
        ? { ...r, partes: r.partes.map((p) => (p.id === atualizada.id ? { ...p, ...atualizada } : p)) }
        : r
    ));
  }, []);

  const aplicarVenda = useCallback((nova) => {
    vendaRef.current = nova;
    setVenda(nova);
    if (nova?.id) sincronizarParte(nova);
  }, [sincronizarParte]);

  // Uma pergunta de cada vez. O `aPerguntar` do state serve o DESENHO (o
  // spinner do botão) e chega tarde de mais para decidir: o relógio dispara
  // fora do render e leria o valor de quando a função foi criada — com a
  // rede lenta, duas ou três perguntas sobre a mesma conta ao mesmo tempo,
  // e a última a chegar a mandar no ecrã, fosse ela a mais recente ou não.
  const perguntaEmCurso = useRef(false);

  // O documento e a FORMA COMO ELE CHEGOU mudam sempre juntos, e por isso
  // mudam-se sempre aqui: um documento recuperado tem de se apresentar de
  // outra maneira — a operadora não viu emissão nenhuma correr bem, viu-a
  // FALHAR, e mostrar-lhe o ecrã normal de sucesso a seguir a isso deixava-a
  // sem perceber se o que está à frente é desta venda ou de outra coisa
  // qualquer. Duas peças de estado soltas acabavam mais cedo ou mais tarde
  // com um documento novo a herdar o "recuperado" do anterior.
  const mostrarDocumento = useCallback((doc, recuperado) => {
    setDocumento(doc || null);
    setDocumentoRecuperado(!!doc && recuperado);
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
    mostrarDocumento(null, false);
    setErroEmissao(null);
    await recarregarVenda();
  }, [recarregarVenda, mostrarDocumento]);

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
      const [respCatalogo, respTipos, respVenda, respRepartidas] = await Promise.all([
        getCatalogoPos(),
        getTiposPagamentoPos(),
        getVendaAberta(caixaId),
        // As pessoas que ficaram por cobrar de uma conta repartida. **O
        // `.catch` não é preguiça — é a razão pela qual esta pergunta é uma
        // rota à parte.** Vai no mesmo `Promise.all` para não custar um
        // segundo ida-e-volta no arranque, mas um `Promise.all` rejeita
        // inteiro à primeira falha: sem isto, uma rota nova a responder mal
        // deixava a operadora no ecrã de erro, sem catálogo e sem a conta em
        // curso — uma pergunta acrescentada a derrubar o balcão. O erro
        // apanha-se aqui e trata-se em baixo, com uma frase; nunca em
        // silêncio.
        getContasRepartidas(caixaId).catch((erroDasPartes) => ({ erroDasPartes })),
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

      // --- O que ficou por cobrar, e que até aqui morria com o browser -------
      //
      // O `reparticao` é estado do React e mais nada: um F5, a tela de
      // descanso, um "Trocar de operador" ou o browser a ir abaixo, e a faixa
      // "Faltam cobrar 2 pessoas de 2 — 14,10 €" desaparecia sem uma palavra,
      // com as duas partes bem `aberta` no servidor. Medido: `abertas no
      // servidor: v-5, v-6, v-7` → o ecrã recuperava `v-7` e mais nada.
      // Agora a lista vem de onde ela sempre esteve guardada — do servidor.
      const daFrente = respVenda.data || null;
      const restaurada = respRepartidas.erroDasPartes
        ? null
        : reparticaoDoServidor((respRepartidas.data || [])[0]);
      if (respRepartidas.erroDasPartes) {
        // Não se afirma que não há partes por cobrar — não se sabe. Diz-se
        // que não se sabe, e diz-se onde é que isso se confirma: o fecho
        // desta caixa lista todas as contas abertas da sessão antes do Z.
        if (respRepartidas.erroDasPartes?.response?.status === 401) {
          operadorInvalido();
          return;
        }
        aplicarVenda(daFrente);
        toast.error(
          'Não foi possível saber se ficaram pessoas por cobrar de uma conta repartida. '
          + 'Se dividiu alguma, confirme-a no fecho da caixa antes de assinar o Z.',
        );
        return;
      }

      setReparticao(restaurada);
      // A `GET /pos/venda/aberta` devolve a venda mais recente do posto — e
      // depois de uma conta ser repartida, a mais recente é uma das PARTES.
      // Pô-la à frente apresentava a parte de uma pessoa como se fosse a conta
      // do balcão. Com a lista recuperada há sítio melhor: as partes, que é
      // exactamente onde o ecrã fica quando se acaba de repartir.
      if (restaurada && ehUmaDasPartes(daFrente, restaurada.partes)) {
        aplicarVenda(null);
        setVista('reparticao');
      } else {
        aplicarVenda(daFrente);
      }

      const porCobrar = partesAbertas(restaurada?.partes);
      if (porCobrar.length > 0) {
        const falta = porCobrar.reduce((soma, p) => soma + centimos(p?.totais?.total), 0);
        toast.error(
          `${porCobrar.length === 1 ? 'Ficou 1 pessoa' : `Ficaram ${porCobrar.length} pessoas`}`
          + ` por cobrar de uma conta repartida — ${euros(falta / 100)}.`,
        );
      }
      // Só há UM lugar no ecrã para uma conta repartida (ver
      // `abrirReparticao`). Com mais do que uma por cobrar — o que só
      // acontece a partir de dados anteriores a essa recusa, ou de dois
      // separadores do POS no mesmo PC — mostra-se a mais recente e DIZ-SE que
      // há outras, em vez de as deixar caladas.
      if ((respRepartidas.data || []).length > 1) {
        toast.error(
          `Há ${respRepartidas.data.length} contas repartidas por cobrar neste posto. O ecrã mostra `
          + 'a mais recente; o fecho da caixa lista-as todas antes do Z.',
        );
      }
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

  // **A conta que nasceu no separador Faturação.** «Copiar para a venda» abre
  // uma conta nova no SERVIDOR (`POST /pos/documentos/{id}/copiar-para-venda`,
  // que por baixo é o `abrir_venda` de sempre) e este ecrã não estava lá para
  // a ver. Sem isto, ele continuava a mostrar o balcão vazio, a operadora
  // tocava num produto e o `POST /pos/venda` respondia 409 sobre uma conta que
  // não estava em ecrã nenhum — o beco do «um posto, uma conta» outra vez,
  // reaberto por um lado novo.
  //
  // Relê-se a conta em vez de a receber por prop: a verdade da conta vem sempre
  // do servidor (`recarregarVenda` chama `GET /pos/venda/aberta`), como em todo
  // este ficheiro. `contasCopiadas` é só a batida do relógio.
  //
  // O `0` inicial não conta — no arranque quem carrega a conta é o
  // `carregarTudo`, e recarregá-la aqui era uma segunda leitura por cada
  // montagem do ecrã.
  useEffect(() => {
    if (!contasCopiadas) return;
    recarregarVenda();
  }, [contasCopiadas, recarregarVenda]);

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
  useEffect(() => {
    if (grelhaRef.current) grelhaRef.current.scrollTop = 0;
  }, [aba, pesquisa]);

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

  // A grelha ROLA, não pagina — foi o que o dono pediu ao ver o ecrã pela
  // primeira vez, e é o gesto que ele já faz no telemóvel. A paginação (que o
  // print do Vendus tem) obrigava a contar páginas de cabeça para achar um
  // artigo; a rolar, procura-se com o polegar e a pesquisa faz o resto. Quem
  // rola é só esta zona: o painel da conta, à direita, fica quieto.
  const grelhaVazia = visiveis.length === 0;

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
      // Só AQUI, depois de o servidor ter aceite a linha: fechar o pedido
      // guiado ao carregar em Gravar deitava fora tudo o que a operadora tinha
      // montado se a chamada falhasse, e obrigava-a a repetir a conversa toda
      // com o cliente à frente.
      setPedidoGuiado(null);
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
    // **A MESMA decisão que apagou o cartão** (`razaoDaGrelhaMorta`, em
    // lib/pos.js), e não uma segunda escrita dela: isto é a garantia por baixo
    // do cartão desligado, e a garantia por baixo dessa é a rota, que responde
    // 409 (`venda.py::abrir_venda`). Com uma conta à frente que não está
    // travada a função devolve `null` e o toque passa — juntar mais um artigo à
    // conta que já existe é o mesmo cliente, e não abre conta nenhuma.
    const razao = razaoDaGrelhaMorta({
      venda: vendaRef.current, partes: reparticao?.partes,
    });
    if (razao) { toast.error(razao); return; }
    // Um produto COM grupos abre o pedido guiado; sem grupos vai direito para a
    // conta, como sempre foi. É a atribuição dos grupos no backoffice — e nada
    // no código — que decide quais os artigos que abrem a conversa ao balcão.
    const grupos = gruposDoProduto(produto);
    if (grupos.length > 0) { setPedidoGuiado({ produto, grupos, linha: null }); return; }
    juntarProduto(produto, { quantidade: 1, opcoes: [] });
  }, [gruposDoProduto, juntarProduto, reparticao]);

  // `manterEdicao` (Task 7): o "Editar pedido" reabre o pedido guiado por
  // CIMA do PosDialogoProduto que já estava aberto — ao gravar, esta função
  // só actualiza opções e resposta de texto, e o desconto/preço que ela
  // estava a escrever ali têm de continuar à vista no MESMO ecrã (é a razão
  // de ser da Task 7: corrigir "esqueci-me da Nutella" não pode escondê-los,
  // ver o "Porquê" do brief). Por omissão o Gravar fecha a edição — é o que
  // o Gravar do PRÓPRIO PosDialogoProduto sempre fez, e continua a fazer.
  const gravarLinha = useCallback((produto, linha, dados, { manterEdicao = false } = {}) => {
    setAGravar(true);
    const terminar = () => setAGravar(false);
    if (linha) {
      executar(async () => {
        try {
          const { data } = await editarLinha(vendaRef.current.id, linha.id, dados);
          aplicarVenda(data);
          if (!manterEdicao) setEmEdicao(null);
          setPedidoGuiado(null);
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

  // O que o pedido guiado devolve são só os dois campos do PEDIDO. Numa linha
  // que já está na conta é isso e nada mais que viaja: o `PedidoEditarLinha`
  // lê-se com `exclude_unset`, e mandar-lhe aqui um `quantidade: 1` de cortesia
  // repunha a 1 uma linha que a operadora tinha posto a 3, sem ninguém pedir.
  const gravarPedidoGuiado = useCallback(({ opcoes, respostas_texto }) => {
    if (!pedidoGuiado) return;
    const { produto, linha } = pedidoGuiado;
    gravarLinha(produto, linha, linha
      ? { opcoes, respostas_texto }
      : { quantidade: 1, opcoes, respostas_texto },
      // Uma linha JÁ na conta só chega aqui pelo "Editar pedido" (Task 7) —
      // o PosDialogoProduto continua aberto por baixo, e é para lá que se
      // volta (ver o comentário do `manterEdicao` em `gravarLinha`).
      { manterEdicao: linha != null });
  }, [pedidoGuiado, gravarLinha]);

  const removerDaConta = useCallback((linha) => executar(async () => {
    // Dois toques seguidos no X da mesma linha (o dedo apressado, o ecrã a
    // responder em 200 ms): quando o segundo chega à sua vez na fila, a linha
    // já não existe e o `DELETE` responderia 404 — um aviso vermelho por cima
    // de uma remoção que CORREU BEM. A fila garante que aqui já se lê a conta
    // depois da primeira remoção.
    if (!vendaRef.current) return;
    if (!(vendaRef.current.linhas || []).some((li) => li.id === linha.id)) return;
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

  // O que se faz depois de uma emissão que NÃO devolveu 200. A regra é uma
  // só, e é a mesma do resto do ficheiro: **não se adivinha nada** — vai-se
  // perguntar ao servidor o que aconteceu MESMO àquela venda, pelo id que o
  // ecrã tem em mãos (`GET /pos/venda/{id}`, que responde em qualquer estado
  // e traz o documento fiscal quando já existe).
  //
  // São dois defeitos, e a mesma correcção para os dois:
  //
  // · **A fatura sai e o ecrã esvazia a conta.** O documento é criado, e é a
  //   RESPOSTA que se perde (o proxy corta aos 30 s porque o Vendus demorou,
  //   o Wi-Fi do balcão pisca). A tentativa seguinte apanha o 409 "esta venda
  //   já foi emitida ou cancelada", e o ecrã lia isso como "ficaste para
  //   trás": um toast que passa, a conta esvaziada, e a operadora sem número,
  //   sem ATCUD e sem talão — o agente de impressão ainda não existe. O gesto
  //   natural a seguir é picar tudo outra vez, e sai uma SEGUNDA Fatura
  //   Simplificada real, que a idempotência do servidor não apanha: é uma
  //   venda nova, com uma ext_ref nova. Se a releitura trouxer documento, é o
  //   documento que se mostra.
  //
  // · **O travão.** `emissao_por_confirmar` é calculado pelo servidor, mas o
  //   ecrã só o recebe quando LÊ a venda. Sem esta releitura a bandeira ficava
  //   colada ao `false` da última resposta boa e o travão nunca chegava a
  //   acender — é esta chamada que liga uma coisa à outra.
  //
  // Deixou de ser preciso reconhecer a frase exacta do servidor (havia aqui
  // uma cópia do `venda.py::_MSG_VENDA_NAO_ABERTA` para distinguir este 409
  // dos outros): perguntar não é ler texto, e a resposta diz mais do que a
  // frase alguma vez disse — o estado, o travão e o documento.
  //
  // O botão fica em "A emitir…" enquanto isto corre (o `setAEmitir(false)` só
  // acontece depois), e é o que se quer: a pergunta é uma leitura de
  // milissegundos no caminho normal, e mostrar já um veredicto que a resposta
  // seguinte vai contradizer é o género de piscar que faz a operadora agir
  // sobre a versão errada.
  const apurarAEmissao = useCallback(async (vendaId, error) => {
    let relida = null;
    try {
      const { data } = await obterVenda(vendaId);
      relida = data;
    } catch (erroDaReleitura) {
      if (erroDaReleitura?.response?.status === 401) { operadorInvalido(); return; }
      // Ficou-se sem saber, e é isso que se diz. `relida` fica `null`, que é
      // o caso mais conservador de todos: nada se afirma sobre a venda e o
      // "não sei" do painel nunca chega a ser despromovido.
      toast.error('Não foi possível confirmar no servidor o que aconteceu a esta venda.');
    }

    // Há documento: a Fatura Simplificada SAIU, seja qual for o erro que
    // trouxe o ecrã até aqui. É a única coisa que interessa mostrar — número
    // e ATCUD bem legíveis, como no caminho feliz.
    if (relida?.documento) {
      aplicarVenda(relida);
      setErroEmissao(null);
      mostrarDocumento(relida.documento, true);
      return;
    }
    // Já não está aberta e não tem documento para mostrar: foi cancelada a
    // meio (o caso normal deste ramo). Aí sim a conta ficou mesmo para trás, e
    // o caminho de sempre está certo — a frase do servidor, a vista da conta e
    // uma releitura. A pergunta é `!== 'aberta'` e não `=== 'cancelada'` de
    // propósito: qualquer outro estado sem documento quer dizer o mesmo — a
    // conta que ela tinha à frente já não existe — e continuar a mostrá-la
    // como se aceitasse produtos era convidar ao toque seguinte.
    if (relida && relida.estado !== 'aberta') {
      await contaFicouParaTras(error);
      return;
    }
    // Continua a ser uma conta: aplica-se o que o servidor acabou de dizer
    // (é daqui que o travão vem) e o erro fica no painel, com o balde
    // decidido também à luz da releitura.
    if (relida) aplicarVenda(relida);
    const { mensagem } = detalhesErroPos(error, 'Não foi possível emitir o documento.');
    setErroEmissao({
      tipo: tipoDoErroDeEmissao(error?.response?.status, mensagem, relida),
      mensagem,
    });
  }, [aplicarVenda, mostrarDocumento, contaFicouParaTras, operadorInvalido]);

  const emitir = useCallback((dados) => {
    if (aEmitir) return;
    setAEmitir(true);
    setErroEmissao(null);
    executar(async () => {
      // O id guarda-se ANTES do pedido, e é por ele que se pergunta depois: é
      // a única coisa que sobrevive a uma emissão que correu mal, e a
      // `vendaRef` pode entretanto ter sido limpa por outro caminho.
      const vendaId = vendaRef.current?.id;
      try {
        const { data } = await finalizarVenda(vendaId, dados);
        aplicarVenda(data);
        mostrarDocumento(data.documento || null, false);
      } catch (error) {
        if (error?.response?.status === 401) { operadorInvalido(); return; }
        // Daqui para a frente já não se está a emitir: o pedido de emissão
        // acabou (mal) e o que corre é a PERGUNTA ao servidor. O botão passa
        // a dizê-lo — ver `aConfirmar`.
        setAConfirmar(true);
        await apurarAEmissao(vendaId, error);
      } finally {
        setAConfirmar(false);
        setAEmitir(false);
      }
    });
  }, [aEmitir, executar, aplicarVenda, mostrarDocumento, operadorInvalido, apurarAEmissao]);

  // --- Entregar a conta travada AO GESTOR ------------------------------------
  //
  // "Servir o cliente seguinte". Tira do ecrã a conta que a operadora não
  // consegue cobrar nem cancelar e deixa o balcão a andar.
  //
  // **Isto era um gesto só do ecrã, e essa era a raiz do pior defeito desta
  // ronda.** Não falava com o servidor: a conta continuava `aberta` lá, e a
  // porta do `POST /pos/venda` deixava abrir a seguinte por causa de uma
  // excepção CALCULADA ("não conta a conta que tiver reserva fiscal viva").
  // Quando o gestor libertasse a reserva, essa excepção deixava de ser verdade
  // sem ninguém escrever nada — e a conta ressuscitava À FRENTE do cliente
  // seguinte, sem marca nenhuma. Medido nas rotas reais: o açaí de 8,99 € do
  // cliente anterior e a Coca-Cola de 2,00 € do novo numa Fatura Simplificada
  // única de 10,99 €.
  //
  // Agora é uma ESCRITA (`POST /pos/venda/{id}/entregar-ao-gestor`) e o
  // servidor GRAVA a marca na venda. A partir dela a conta sai ao mesmo tempo
  // do conjunto da porta e do conjunto do ecrã, e não volta ao balcão nem
  // depois de o gestor libertar a reserva: resolve-se onde ela está, na lista
  // dele.
  //
  // **E o ecrã volta a PERGUNTAR ao servidor o que fica à frente**, em vez de
  // assumir que fica vazio. É a outra metade da mesma correcção: podia haver
  // outra conta deste posto escondida atrás da travada (a que a operadora não
  // via porque o ecrã só mostra a mais recente), e limpar o ecrã por conta
  // própria punha os cartões vivos por cima de uma conta que a rota ia recusar
  // — 409 ao primeiro produto, com o cliente à frente. `recarregarVenda` põe à
  // frente o que o servidor disser, que é exactamente o mesmo conjunto que a
  // porta conta.
  //
  // **Só serve a conta travada, e é o servidor que o garante:**
  // `venda.py::entregar_ao_gestor` recusa com 409 uma conta que não esteja
  // travada — uma conta normal acaba aqui, cobrada ou cancelada. Por isso só a
  // `FaixaContaTravada` chama isto, e por isso um bundle antigo a chamar sobre
  // outra coisa não abre porta nenhuma.
  const largarContaTravada = useCallback(() => executar(async () => {
    const largada = vendaRef.current;
    if (!largada?.id) return;
    try {
      await entregarContaAoGestor(largada.id);
    } catch (error) {
      // Não se larga nada: a conta continua à frente, com a faixa e os dois
      // botões. Limpar o ecrã aqui era afirmar que ela é do gestor quando o
      // servidor acabou de dizer que não — e a conta ficava invisível dos dois
      // lados.
      falhou(error, 'Não foi possível entregar esta conta ao gestor.');
      return;
    }
    setContasTravadasLargadas((largadas) => (
      // Sem repetidos: uma conta que o arranque tenha voltado a pôr à frente
      // pode ser entregue duas vezes, e duas notas iguais no painel eram duas
      // contas onde só há uma.
      largadas.some((c) => c.id === largada.id) ? largadas : [...largadas, {
        id: largada.id,
        total: largada.totais?.total ?? null,
        // Como é que esta conta ficou travada, para a nota não afirmar mais do
        // que se soube no momento em que ela foi entregue.
        peloServidor: contaTravada(largada),
      }]
    ));
    setEmEdicao(null);
    setErroEmissao(null);
    mostrarDocumento(null, false);
    setVista('conta');
    // A conta que fica à frente vem do SERVIDOR — pode ser `null` (o balcão
    // ficou livre) ou outra conta deste posto que estava escondida atrás da
    // travada. `recarregarVenda` chama `aplicarVenda(data || null)`.
    await recarregarVenda();
    toast.success('Conta entregue ao gestor — fica na lista dele, no backoffice. Toque num produto para começar a conta do cliente seguinte.');
  }), [executar, falhou, mostrarDocumento, recarregarVenda]);

  // --- Dividir e separar a conta ----------------------------------------------
  //
  // Três amigos, dois açaís e uma Coca-Cola: ou dividem por igual, ou cada um
  // paga o que consumiu — e cada um leva a SUA fatura.
  //
  // **Nada aqui é um caminho novo de emissão.** Cada parte que o servidor
  // devolve é uma venda normal deste módulo, com a sua referência
  // determinística, a sua reserva atómica e a sua idempotência: cobrá-la é o
  // `emitir` de sempre com a parte à frente, e deitá-la fora é o
  // `cancelarVenda` de sempre. É essa decisão — do lado do servidor e deste —
  // que mantém tudo o que foi endurecido no núcleo fiscal a valer para as
  // partes sem uma linha nova.

  // **Há UM lugar para uma repartição — este `reparticao` — e por isso não se
  // abre uma segunda por cima de uma que ainda tem gente por pagar.** Não era
  // "começar outra": era apagar a primeira. Medido: separada uma conta de
  // 16,41 € em 8,41 + 8,00, as duas por cobrar, bastava começar a conta do
  // cliente seguinte e tocar em "Dividir Conta" **só para ver a previsão** —
  // a `mae` e as `partes` passavam a ser as da conta nova, e recuar com a
  // seta (`sairDaReparticao`, que com `partes` a `null` deita a repartição
  // fora) levava com ela a faixa "Faltam cobrar 2 pessoas de 2". As duas
  // partes continuavam abertas no servidor, com 16,41 € por receber, e o ecrã
  // não voltava a dizer uma palavra sobre elas.
  //
  // Recusa-se e diz-se porquê, que é a mesma regra do resto do ficheiro. Em
  // uso normal isto nunca dispara: o botão que traz aqui já vem desligado com
  // a razão à vista (`impedeRepartir`, no PosFinalizar). Está aqui na mesma
  // porque um botão desligado é uma cortesia e isto é a garantia — nenhum
  // caminho novo pode entrar por baixo dele e apagar dinheiro por receber.
  //
  // Partes já TODAS resolvidas (cobradas ou canceladas) não impedem nada: não
  // há dinheiro por receber nenhum e não há nada para perder de vista.
  const abrirReparticao = useCallback((modo) => {
    if (!vendaRef.current) return;
    const razao = razaoDeNaoRepartir(partesAbertas(reparticao?.partes));
    if (razao) {
      toast.error(razao);
      return;
    }
    setReparticao({ modo, mae: vendaRef.current, partes: null });
    setVista('reparticao');
  }, [reparticao]);

  const repartir = useCallback(({ modo, partes }) => {
    if (aRepartir) return;
    // Trancado JÁ, e não lá dentro da fila: a tarefa pode ficar atrás de
    // outra escrita e, até ela arrancar, o botão continuava vivo — dois
    // toques seguidos repartiam a conta duas vezes (o segundo apanharia o 409
    // da mãe já `separada`, mas o ecrã não pode CONVIDAR a isso).
    setARepartir(true);
    executar(async () => {
      // A mãe é a conta que está à frente — a mesma de que o ecrã fez a
      // previsão. Guarda-se o id ANTES do pedido, como no `emitir`.
      const maeId = vendaRef.current?.id;
      if (!maeId) { setARepartir(false); return; }
      try {
        const { data } = modo === 'dividir'
          ? await dividirConta(maeId, partes)
          : await separarConta(maeId, partes);
        setReparticao({ modo, mae: data.conta_mae, partes: data.partes || [] });
        // A mãe deixou de ser uma conta: passou a `separada` e não aceita
        // produtos, alterações, descontos nem cancelamento. Tirá-la da frente é
        // o que impede o toque seguinte de ir bater num 409 — e o que faz o
        // primeiro produto abrir uma conta NOVA, se ela quiser servir outra
        // pessoa antes de acabar de cobrar estas.
        aplicarVenda(null);
        setEmEdicao(null);
        toast.success(
          modo === 'dividir'
            ? `Conta dividida em ${(data.partes || []).length} partes. Cobre uma de cada vez.`
            : `Conta separada em ${(data.partes || []).length} partes. Cobre uma de cada vez.`,
        );
      } catch (error) {
        const status = error?.response?.status;
        if (status === 401) { operadorInvalido(); return; }
        // Sem resposta, o pedido pode ter sido gravado do outro lado — e o que
        // estaria gravado são N contas prontas a emitir. Não se afirma nada:
        // relê-se a conta pelo id que se tem em mãos, e é o estado dela que diz
        // o que aconteceu. `separada` quer dizer que a repartição foi mesmo
        // feita, e as partes existem sem este ecrã as ter visto — aí a única
        // coisa honesta é mandar chamar o gestor, que as encontra na sessão.
        if (semRespostaPos(error)) {
          toast.error(
            `${ehTimeoutPos(error)
              ? `O servidor não respondeu em ${SEGUNDOS_DE_ESPERA} segundos.`
              : 'Não houve resposta do servidor.'} Não se sabe se a conta chegou a ser repartida — confirme antes de repetir.`,
          );
          try {
            const { data } = await obterVenda(maeId);
            if (data?.estado === 'separada') {
              toast.error(
                'A conta FOI repartida no servidor, mas as partes não chegaram a este ecrã. '
                + 'Não reparta outra vez: chame o gestor com a referência desta conta.',
              );
              setReparticao(null);
              setVista('conta');
              aplicarVenda(null);
              return;
            }
            if (data?.estado !== 'aberta') {
              // Já não é uma conta: alguém a emitiu ou cancelou primeiro. Não
              // chegou a ser repartida, e a previsão que está no ecrã é sobre
              // uma conta que já não existe — não se deixa lá à frente, com um
              // botão que só pode dar erro.
              toast.error('Esta conta já não está aberta — não chegou a ser repartida.');
              setReparticao(null);
              setVista('conta');
              aplicarVenda(null);
              return;
            }
            aplicarVenda(data);
          } catch (erroDaReleitura) {
            toast.error('Também não foi possível reler esta conta — não reparta outra vez sem confirmar.');
          }
          return;
        }
        // O servidor RESPONDEU e recusou. As mensagens dele são as boas: dizem
        // se a conta mudou por baixo (409), se não fecha ao cêntimo ou se há
        // artigos por atribuir (422), e o que fazer a seguir em cada caso.
        toast.error(detalhesErroPos(error, 'Não foi possível repartir esta conta.').mensagem);
        if (status === 409) {
          // A conta ficou para trás (emitida ou cancelada noutro sítio), ou
          // mudou por baixo. Nos dois casos a previsão que está no ecrã já não
          // vale nada: relê-se e volta-se ao balcão.
          setReparticao(null);
          setVista('conta');
          await recarregarVenda();
        }
      } finally {
        setARepartir(false);
      }
    });
  }, [aRepartir, executar, aplicarVenda, operadorInvalido, recarregarVenda]);

  // Cobrar uma parte é pôr a parte à frente e ir ao finalizar de sempre —
  // sem um segundo caminho de emissão, que é a razão de ser de tudo isto.
  //
  // **O lugar da conta em curso é UM, e aqui ele está livre.** Houve um tempo
  // em que este `aplicarVenda(parte)` largava em silêncio a conta que a
  // operadora tinha começado enquanto as partes esperavam — `aberta` no
  // servidor e invisível no ecrã. Essa conta deixou de poder existir: enquanto
  // houver partes por resolver neste posto, `venda.py::abrir_venda` recusa
  // abrir a seguinte com 409, e o que está à frente é sempre uma das partes ou
  // nada. Não é o ecrã que o garante — é a rota.
  const cobrarParte = useCallback((parte) => {
    if (!parte) return;
    aplicarVenda(parte);
    setErroEmissao(null);
    mostrarDocumento(null, false);
    setEmEdicao(null);
    setVista('finalizar');
  }, [aplicarVenda, mostrarDocumento]);

  // A saída para quem não paga. É o `cancelarVenda` de sempre, sobre uma venda
  // normal — e o ecrã diz o que isso significa antes de o fazer (o diálogo do
  // PosReparticao): os artigos desta parte saem sem fatura e sem dinheiro.
  const cancelarParte = useCallback((parte) => executar(async () => {
    if (!parte?.id) return;
    setACancelarParte(parte.id);
    try {
      const { data } = await cancelarVenda(parte.id);
      sincronizarParte(data);
      toast.success('Parte cancelada. Os artigos dela saem sem fatura e sem dinheiro.');
    } catch (error) {
      if (error?.response?.status === 401) { operadorInvalido(); return; }
      toast.error(detalhesErroPos(error, 'Não foi possível cancelar esta parte.').mensagem);
      // O ecrã não afirma nada sobre o que aconteceu à parte: vai perguntar. É
      // a mesma disciplina do `apurarAEmissao` — um 409 aqui quer dizer que
      // nasceu uma reserva fiscal para esta parte, e é o servidor que sabe em
      // que estado ela ficou.
      try {
        const { data } = await obterVenda(parte.id);
        sincronizarParte(data);
      } catch (erroDaReleitura) {
        toast.error('Também não foi possível reler esta parte — o que está no ecrã pode não estar actualizado.');
      }
    } finally {
      setACancelarParte(null);
    }
  }), [executar, sincronizarParte, operadorInvalido]);

  // Sair do ecrã da repartição. Antes de repartir não há nada feito e a
  // escolha deita-se fora inteira (a seta volta ao finalizar); com as partes
  // já criadas, sair é ir servir o cliente seguinte — e a `reparticao` fica,
  // para a nota do painel da conta poder dizer o que falta receber e para
  // haver caminho de volta.
  //
  // O `setReparticao(null)` de baixo só é seguro por causa da recusa do
  // `abrirReparticao`: sem ela, `partes` a `null` podia ser uma previsão nova
  // ESCRITA POR CIMA de uma repartição com gente por pagar, e era aqui que as
  // partes dessa gente desapareciam do ecrã. Com a recusa, `partes` a `null`
  // quer dizer sempre o que parece — uma escolha que ainda não fez nada a
  // ninguém.
  const sairDaReparticao = useCallback(() => {
    if (reparticao?.partes) { setVista('conta'); return; }
    setReparticao(null);
    setVista('finalizar');
  }, [reparticao]);

  // Todas as partes resolvidas (cobradas ou canceladas): a conta acabou, e só
  // agora é que há cliente seguinte. É o botão "Nova Venda" do ecrã das partes.
  //
  // O que está à frente aqui é a última parte cobrada, ou nada — nunca uma
  // conta do balcão começada entretanto, porque enquanto houvesse partes por
  // resolver o `venda.py::abrir_venda` recusava abri-la. O `aplicarVenda(null)`
  // limpa o ecrã para a venda seguinte, que é o que o botão promete.
  const terminarReparticao = useCallback(() => {
    aplicarVenda(null);
    setReparticao(null);
    mostrarDocumento(null, false);
    setErroEmissao(null);
    setVista('conta');
  }, [aplicarVenda, mostrarDocumento]);

  // --- A saída da conta travada -----------------------------------------------

  // Vai PERGUNTAR ao servidor o que é feito de uma conta sobre a qual este
  // ecrã tem uma dúvida — a mesma pergunta do `apurarAEmissao`
  // (`GET /pos/venda/{id}`), só que agora sem erro nenhum a acompanhá-la.
  //
  // É esta função que fecha o beco sem saída. O travão vem do servidor, mas o
  // ecrã só o recebia quando LIA a venda — e depois de a emissão falhar nada
  // voltava a lê-la: o gestor libertava a reserva no backoffice, o servidor
  // passava a responder `emissao_por_confirmar: false`, e o ecrã ficava
  // travado à mesma até alguém se lembrar do F5 (medido: passado mais de um
  // segundo, leituras da conta 1 → 1, delta 0). Agora há duas maneiras de a
  // chamar, e as duas fazem falta: o relógio (a seguir), para o ecrã se
  // reparar sozinho enquanto ninguém lhe toca, e o botão da faixa, para quem
  // não quer esperar cinco segundos com o cliente à frente.
  //
  // `automatica` distingue-as numa coisa só, e é uma coisa que interessa: as
  // perguntas do relógio calam-se quando falham (uma rede em baixo dava um
  // toast a cada 5 segundos, para sempre) e quando não há novidade nenhuma.
  // As dela respondem SEMPRE alguma coisa — um botão que não dá sinal de vida
  // é um botão em que se carrega dez vezes.
  const perguntarPelaConta = useCallback(async (vendaId, { automatica = false } = {}) => {
    if (!vendaId || perguntaEmCurso.current) return;
    perguntaEmCurso.current = true;
    setAPerguntar(true);
    try {
      const { data } = await obterVenda(vendaId);
      if (contaTravada(data)) {
        if (!automatica) {
          toast.error('A conta continua travada — a emissão ainda não foi confirmada no servidor.');
        }
        return;
      }
      // Destravou. Esta pergunta é SEMPRE sobre a conta que está à frente dela
      // — só a faixa e o relógio a fazem, e os dois seguem `venda` —, por isso
      // o que o servidor acabou de dizer manda no ecrã sem mais nenhuma
      // pergunta. Uma conta travada LARGADA não é perguntada daqui: a partir
      // do momento em que ela sai da frente é do gestor, e resolve-se no
      // backoffice.
      if (data.documento) {
        // A Fatura Simplificada saiu. Mesmo desfecho do `apurarAEmissao`, e
        // pela mesma razão: número e ATCUD à vista valem mais do que qualquer
        // frase, e é o que evita que ela pique tudo outra vez.
        aplicarVenda(data);
        setErroEmissao(null);
        setEmEdicao(null);
        mostrarDocumento(data.documento, true);
        setVista('finalizar');
        return;
      }
      if (data.estado !== 'aberta') {
        // Já não é uma conta: foi cancelada (ou resolvida) do lado do gestor.
        aplicarVenda(null);
        setErroEmissao(null);
        setEmEdicao(null);
        mostrarDocumento(null, false);
        setVista('conta');
        toast.success('A conta que estava travada já não está aberta — foi resolvida. A próxima nasce ao primeiro produto.');
        return;
      }
      // Aberta e sem emissão nenhuma por confirmar: é o servidor a dizer que
      // não há Fatura Simplificada nenhuma a nascer nesta venda (ver
      // `contaLimpaNoServidor`). A conta volta ao normal.
      aplicarVenda(data);
      // A dúvida que congelava o ecrã fica RESOLVIDA, e resolvida com o que o
      // servidor acabou de dizer: passa ao balde 'nada-saiu', que é o painel
      // que explica a falha e convida a emitir outra vez — em vez de
      // desaparecer sem uma palavra, depois de ela ter lido "não sabemos se a
      // fatura saiu".
      setErroEmissao((anterior) => (
        duvidaPorApurar(anterior) ? { tipo: 'nada-saiu', mensagem: anterior.mensagem } : anterior
      ));
      toast.success('Conta destrancada: o servidor confirma que não há nenhuma emissão por confirmar.');
    } catch (error) {
      if (error?.response?.status === 401) { operadorInvalido(); return; }
      if (!automatica) {
        toast.error('Não foi possível perguntar ao servidor por esta conta — tente daqui a pouco.');
      }
    } finally {
      perguntaEmCurso.current = false;
      setAPerguntar(false);
    }
  }, [aplicarVenda, mostrarDocumento, operadorInvalido]);

  // A conta sobre a qual há uma dúvida por apurar — o id, ou `null`. É o que
  // liga e desliga o relógio de baixo, e é um ID e não um objecto de
  // propósito: a conta muda de identidade a cada resposta do servidor, e com
  // ela nas dependências o relógio reiniciava-se a cada releitura e nunca
  // chegava a disparar.
  //
  // As duas razões contam, e não é o mesmo travão: `contaTravada` é o que o
  // servidor SABE (há reserva fiscal e a venda ainda não está emitida);
  // `duvidaPorApurar` é o que o ecrã NÃO conseguiu confirmar (a emissão falhou
  // e a releitura também). Na segunda não há sequer bandeira do servidor para
  // apagar — e é precisamente por isso que ela tem de continuar a perguntar.
  const contaComDuvida = venda && (contaTravada(venda) || duvidaPorApurar(erroEmissao))
    ? venda.id
    : null;

  // O relógio que repara o ecrã sozinho. Nasce quando a dúvida aparece, morre
  // quando ela se resolve (ou quando este ecrã se desmonta) — nunca um
  // `setInterval` esquecido a correr o dia inteiro sobre um balcão que não tem
  // dúvida nenhuma.
  //
  // Não corre durante a emissão (`aEmitir`): nesse momento já há uma pergunta
  // ao servidor a caminho, a do `apurarAEmissao`, e duas respostas a
  // escreverem no mesmo ecrã acabam com a mais antiga a chegar por último.
  //
  // Segue a conta que está À FRENTE dela, e só essa: uma conta travada LARGADA
  // sai daqui (o `venda` passa a ser a nova) e deixa de ser perguntada. É de
  // propósito — a partir daí ela está a servir clientes, e a conta largada é do
  // gestor, que a resolve na lista de contas por cobrar do backoffice
  // (`FatReservasPresas.js`). A nota do painel dá-lhe a referência e mais nada:
  // não há nada que a operadora possa fazer com a resposta.
  //
  // **O caso simétrico — a conta que PASSA a estar travada enquanto ela olha
  // para ela — não precisa de relógio nenhum, e é por isso que este só corre
  // num sentido.** Uma conta passa a travada porque nasceu uma reserva fiscal
  // para ela, e a partir desse instante o servidor recusa com 409 TODAS as
  // escritas (`venda.py::_garante_sem_emissao`): o toque seguinte na conta —
  // um produto, uma quantidade, o desconto, o cancelar — cai no `falhou`, que
  // manda o 409 para o `contaFicouParaTras`, que RELÊ a conta e acende a
  // faixa. Ou seja: o ecrã aprende que ficou travada no exacto momento em que
  // isso lhe passa a fazer diferença, sem perguntar nada entretanto.
  useEffect(() => {
    if (!contaComDuvida || aEmitir) return undefined;
    const relogio = setInterval(
      () => { perguntarPelaConta(contaComDuvida, { automatica: true }); },
      MS_ENTRE_PERGUNTAS,
    );
    return () => clearInterval(relogio);
  }, [contaComDuvida, aEmitir, perguntarPelaConta]);

  // A seta de voltar do finalizar E o "Nova Venda" de depois de emitir são o
  // mesmo callback (é o contrato do PosFinalizar).
  //
  // A conta só se LARGA quando o servidor já a deu por terminada, e é a
  // resposta dele que decide — não a presença de um documento no ecrã. Com o
  // `if (documento)` sozinho, o "Nova Venda" do documento RECUPERADO destrancava
  // a conta por um caminho que não é o servidor: o backend grava o documento
  // ANTES de marcar a venda `emitida` (`fiscal.py::_gravar_documento`, duas
  // escritas), por isso a releitura pode trazer um documento com a venda ainda
  // `aberta` e a reserva viva — e um toque em "Nova Venda" fazia a faixa
  // "Conta travada" desaparecer, os cartões voltarem à vida e o toque seguinte
  // abrir uma SEGUNDA conta no servidor, ficando a primeira travada e
  // invisível, a bloquear o fecho de caixa dessa noite.
  //
  // A dúvida por apurar também não se limpa aqui: o painel do finalizar dizia
  // "não sabemos se a fatura saiu", a seta de voltar apagava essa memória, e
  // dois toques punham o EMITIR aceso outra vez sobre a mesma venda. Enquanto
  // o servidor não disser o que aconteceu, a dúvida acompanha a conta —
  // quem a resolve é o `perguntarPelaConta`, não um botão de navegação.
  const voltarDoFinalizar = useCallback(() => {
    // A conta de onde se volta lê-se ANTES de se largar seja o que for: é ela
    // que decide para onde se vai, e o `aplicarVenda(null)` logo a seguir
    // apagava-a.
    const daFrente = vendaRef.current;
    const porApurar = duvidaPorApurar(erroEmissao) || contaTravada(daFrente);
    // A pergunta que faltava, e que custou uma conta: esta conta é UMA DAS
    // PARTES em cobrança, ou é uma venda do balcão que nada tem a ver com
    // elas? A condição era só "há partes por cobrar", e com partes vivas a
    // seta de voltar do finalizar de uma conta NORMAL — a Embalagem de 0,15 €
    // do cliente seguinte — largava-a (`aplicarVenda(null)`) e aterrava em
    // "Cobrar as partes" do cliente ANTERIOR. A conta ficava `aberta` no
    // servidor, sem uma palavra no ecrã e sem caminho de volta, e o toque
    // seguinte abria outra por cima dela — órfã e invisível. Essa conta deixou
    // de poder existir (com partes por resolver, `venda.py::abrir_venda` recusa
    // abrir a seguinte com 409), mas a pergunta continua a ser a mesma: daqui
    // não se larga nenhuma conta que o servidor ainda dê por aberta, e a nota
    // das partes (`AvisoPartesPorCobrar`) continua a dizer o que falta receber
    // por cima da conta que ficou à frente.
    //
    // A mesma linha fazia o "Nova Venda" de uma venda já emitida aterrar nas
    // partes de outra pessoa — um botão a dizer uma coisa e a fazer outra.
    const ehParte = ehUmaDasPartes(daFrente, reparticao?.partes);
    if (documento && daFrente?.estado !== 'aberta') aplicarVenda(null);
    mostrarDocumento(null, false);
    setErroEmissao((anterior) => (duvidaPorApurar(anterior) ? anterior : null));
    // A cobrar uma PARTE, o que está atrás não é o balcão: são as outras
    // pessoas da mesma conta. Voltar ao balcão daqui era perder de vista o que
    // falta receber, com o cliente seguinte já à frente.
    //
    // Com uma dúvida por apurar é o contrário, e por isso ela vem primeiro: a
    // conta travada tem de continuar à frente dela, no painel da conta, onde a
    // `FaixaContaTravada` explica o que se passa e dá as duas saídas. Mandá-la
    // para a lista das partes deixava a dúvida órfã — sem faixa, sem relógio a
    // perguntar ao servidor, e com o EMITIR de outra parte à distância de um
    // toque.
    if (ehParte && !porApurar) {
      // A parte sai da frente, mas não desaparece: está na lista para onde se
      // vai a seguir, com o estado que o servidor lhe deu.
      aplicarVenda(null);
      setVista('reparticao');
      return;
    }
    setVista('conta');
  }, [documento, aplicarVenda, mostrarDocumento, erroEmissao, reparticao]);

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

  // O TRAVÃO desta conta. A fonte principal é a bandeira que o servidor
  // calcula (`venda.py::_emissao_por_confirmar`) e devolve em todas as
  // respostas de venda: derivada da conta, sobrevive à seta de voltar, ao F5,
  // à tela de descanso dos 5 minutos e ao outro PC, porque em todos esses
  // casos o ecrã volta a LER a conta ao servidor.
  const travadaPeloServidor = contaTravada(venda);

  // ... e a segunda razão, que não é a mesma coisa nem a substitui: uma dúvida
  // por apurar (`duvidaPorApurar`) é o ecrã a não ter conseguido confirmar
  // NADA — a emissão falhou e a releitura da venda também. Aí não há bandeira
  // do servidor para ler, e tratar a ausência de bandeira como "está tudo
  // bem" era o furo por onde a conta voltava a ficar editável e o EMITIR
  // aceso, por cima de uma Fatura Simplificada que pode ter saído. Menos
  // informação nunca pode dar mais liberdade do que mais informação: as duas
  // razões congelam o ecrã da mesma maneira, e a faixa diz qual delas é.
  const travada = travadaPeloServidor || duvidaPorApurar(erroEmissao);

  // A conta que está à frente é uma das partes em cobrança? Se for, o
  // finalizar tem de o DIZER — o ecrã de uma parte é indistinguível do de uma
  // venda normal (um total mais pequeno e mais nada), e cobrar 3,00 € a quem
  // devia 8,99 € é um engano que só aparece no fecho da caixa.
  //
  // `restanteCentimos` é o que fica por receber DEPOIS desta, já sem ela: é a
  // pergunta seguinte de quem está a cobrar três pessoas à vez.
  const parteEmCobranca = useMemo(() => {
    const lista = reparticao?.partes;
    if (!lista || !venda?.id) return null;
    const i = lista.findIndex((p) => p.id === venda.id);
    if (i < 0) return null;
    return {
      numero: i + 1,
      de: lista.length,
      restanteCentimos: lista.reduce(
        (soma, p) => (p.estado === 'aberta' && p.id !== venda.id ? soma + centimos(p.totais?.total) : soma),
        0,
      ),
    };
  }, [reparticao, venda]);

  // As partes que ficaram por cobrar enquanto ela está no balcão. `null`
  // quando não há repartição nenhuma viva, ou quando já não falta cobrar
  // ninguém — nesse caso não há dinheiro por receber e a nota só ocupava o
  // painel.
  const partesPorCobrar = useMemo(() => {
    const lista = reparticao?.partes;
    if (!lista) return null;
    // A MESMA pergunta do travão do `abrirReparticao` e da razão que desliga
    // os botões de repartir — uma definição só, em `lib/pos.js`.
    const abertas = partesAbertas(lista);
    if (abertas.length === 0) return null;
    return {
      porCobrar: abertas.length,
      deQuantas: lista.length,
      faltaCentimos: abertas.reduce((soma, p) => soma + centimos(p.totais?.total), 0),
    };
  }, [reparticao]);

  // A razão por que os dois botões de repartir estão desligados no finalizar,
  // ou `null`. É a MESMA frase e a MESMA pergunta que fazem o
  // `abrirReparticao` recusar: assim não há forma de o botão convidar ao que a
  // função recusa, nem de a função recusar sem o ecrã ter dito porquê antes do
  // toque.
  const impedeRepartir = razaoDeNaoRepartir(partesAbertas(reparticao?.partes));

  // Porque é que a grelha de produtos está morta — ou `null` quando não está.
  // A decisão inteira vive em `lib/pos.js::razaoDaGrelhaMorta`, e é a MESMA que
  // o `tocarProduto` faz por baixo do cartão: escritas em separado, o cartão e
  // o toque acabam a dizer coisas diferentes sobre a mesma conta.
  //
  // `travadaPeloServidor` não entra aqui: o que desliga a grelha é o travão da
  // conta, e `contaTravada` (dentro do lib) lê-o da venda. O `travada` local
  // acrescenta-lhe a dúvida por apurar do ECRÃ, e essa continua a valer para a
  // faixa — mas a faixa é outra coisa.
  const bloqueioDaGrelha = travada
    ? MSG_CONTA_TRAVADA_CURTA
    : razaoDaGrelhaMorta({ venda, partes: reparticao?.partes });

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
          aConfirmar={aConfirmar}
          documento={documento}
          documentoRecuperado={documentoRecuperado}
          erroEmissao={erroEmissao}
          parte={parteEmCobranca}
          onVoltar={voltarDoFinalizar}
          onAplicarDesconto={aplicarDesconto}
          onEmitir={emitir}
          onDividir={() => abrirReparticao('dividir')}
          onSeparar={() => abrirReparticao('separar')}
          impedeRepartir={impedeRepartir}
        />
      </div>
    );
  }

  // O ecrã da repartição toma o ecrã TODO, pela mesma razão do finalizar: a
  // atribuição artigo a artigo e a conta de cada pessoa lado a lado precisam
  // da largura, e a grelha ao lado só convidaria a picar mais um artigo numa
  // conta que está a ser repartida.
  if (vista === 'reparticao' && reparticao) {
    return (
      <div className="flex-1 min-h-0 bg-card">
        <PosReparticao
          mae={reparticao.mae}
          modo={reparticao.modo}
          partes={reparticao.partes}
          aRepartir={aRepartir}
          aCancelarParte={aCancelarParte}
          onModo={(modo) => setReparticao((r) => (r ? { ...r, modo } : r))}
          onVoltar={sairDaReparticao}
          onRepartir={repartir}
          onCobrarParte={cobrarParte}
          onCancelarParte={cancelarParte}
          onTerminar={terminarReparticao}
        />
      </div>
    );
  }

  return (
    // Área de trabalho CONTIDA (`max-w`), como no POS do Vendus: num monitor
    // grande a grelha esticada até à borda dá cartões enormes e obriga a
    // percorrer o ecrã todo com os olhos entre o artigo e a conta. A barra de
    // cima fica à largura toda de propósito — é o que ancora o ecrã.
    <div className="flex-1 min-h-0 w-full max-w-[1600px] mx-auto flex flex-col lg:flex-row">
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

        <div ref={grelhaRef} className="flex-1 min-h-0 overflow-y-auto p-3">
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
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-2.5">
              {visiveis.map((produto) => (
                <CartaoProduto
                  key={produto.id}
                  produto={produto}
                  onTocar={tocarProduto}
                  bloqueio={bloqueioDaGrelha}
                />
              ))}
            </div>
          )}
        </div>

      </section>

      <aside className="w-full lg:w-[23rem] xl:w-[26rem] shrink-0 min-h-0 border-t lg:border-t-0 lg:border-l bg-card flex flex-col">
        {emEdicao && produtoEmEdicao ? (
          <PosDialogoProduto
            produto={produtoEmEdicao}
            grupos={gruposDoProduto(produtoEmEdicao)}
            linha={linhaEmEdicao}
            aGravar={aGravar}
            onGravar={(dados) => gravarLinha(produtoEmEdicao, linhaEmEdicao, dados)}
            onVoltar={() => setEmEdicao(null)}
            onRemover={linhaEmEdicao ? () => removerDaConta(linhaEmEdicao) : undefined}
            // "Editar pedido" (Task 7): volta a abrir o MESMO pop-up do
            // pedido guiado, agora com a `linha` preenchida — é o caminho
            // curto para corrigir "esqueci-me da Nutella" sem apagar a linha
            // e picar tudo de novo. Só existe quando há uma linha para
            // editar; o PosDialogoProduto só mostra o botão quando, além
            // disso, o produto tem grupos (é ele que decide se há pedido
            // guiado nenhum para reabrir).
            onEditarPedido={linhaEmEdicao ? () => setPedidoGuiado({
              produto: produtoEmEdicao,
              grupos: gruposDoProduto(produtoEmEdicao),
              linha: linhaEmEdicao,
            }) : undefined}
          />
        ) : (
          <PainelConta
            venda={venda}
            /* A caixa em que o ECRÃ está, para o painel poder dizer quando a
               conta à frente veio de outra (`contaDeOutraCaixa`). Passa-se o
               objecto e não só o id porque a nota escreve o NOME desta — e
               isto não é o `useEffect` do catálogo, onde passar a caixa
               inteira recarregava o ecrã a meio de uma venda. */
            caixa={caixa}
            aEscrever={escritas > 0}
            travada={travada}
            travadaPeloServidor={travadaPeloServidor}
            /* Uma conta travada largada só se anuncia enquanto for OUTRA que
               não a que está à frente: se o ecrã tiver voltado a ela (o
               arranque relê a conta em curso e o `GET /pos/venda/aberta`
               devolveu-a outra vez), quem fala dela é a faixa — e duas caixas
               a dizer o mesmo liam-se como dois problemas diferentes. */
            contasTravadasLargadas={contasTravadasLargadas.filter((c) => c.id !== venda?.id)}
            aPerguntar={aPerguntar}
            partesPorCobrar={partesPorCobrar}
            onPerguntar={() => perguntarPelaConta(venda?.id)}
            onLargar={largarContaTravada}
            onVoltarAsPartes={() => setVista('reparticao')}
            onTocarLinha={(linha) => setEmEdicao({ produtoId: linha.produto_id, linhaId: linha.id })}
            /* O X de cada linha. É o MESMO `removerDaConta` do botão
               «Remover da conta» do diálogo — um caminho só, com as
               guardas todas do servidor por baixo. */
            onRemoverLinha={removerDaConta}
            /* A dúvida por apurar NÃO se limpa aqui, pela mesma razão da seta
               de voltar (ver `voltarDoFinalizar`): ir ao ecrã de pagamento não
               é saber o que aconteceu à emissão anterior, e limpá-la punha o
               EMITIR aceso outra vez à distância de dois toques. */
            onFinalizar={() => {
              setErroEmissao((anterior) => (duvidaPorApurar(anterior) ? anterior : null));
              mostrarDocumento(null, false);
              setVista('finalizar');
            }}
            onCancelar={() => setAConfirmarCancelar(true)}
            razaoDeNaoImprimirPedido={razaoDeNaoImprimirPedido}
            onImprimirPedido={imprimirPedido}
            aImprimirPedido={aImprimirPedido}
          />
        )}
      </aside>

      {/* Fora do <aside> de propósito: o pedido guiado FLUTUA por cima do ecrã
          inteiro, com a grelha e a conta à vista por trás — ao contrário do
          diálogo do produto, que substitui o painel direito.

          A `key` é o que impede o estado de sobreviver a uma troca de produto
          ou de linha. Hoje o pop-up desmonta-se sempre entre pedidos e o
          estado morre com ele; mas quem lhe trocar o produto por baixo SEM o
          fechar — que é o que corrigir uma linha vai fazer — encontrava lá os
          toppings do pedido anterior. É o mesmo defeito que o
          PosDialogoProduto teve de resolver à mão com o `arranque`. */}
      {pedidoGuiado && (
        <PosPedidoGuiado
          key={`${pedidoGuiado.produto?.id || ''}|${pedidoGuiado.linha?.id || ''}`}
          produto={pedidoGuiado.produto}
          grupos={pedidoGuiado.grupos}
          linha={pedidoGuiado.linha}
          aGravar={aGravar}
          onGravar={gravarPedidoGuiado}
          onFechar={() => setPedidoGuiado(null)}
        />
      )}

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
