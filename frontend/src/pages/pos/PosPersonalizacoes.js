import React from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { numeroPos as euros } from '@/lib/pos';

// O painel das personalizações do POS (Plano 2C, Task 3) — o que se abre em
// "Editar Personalizações" no diálogo do produto, e logo ao tocar num
// produto que tenha um grupo obrigatório.
//
// Totalmente CONTROLADO: não guarda escolha nenhuma em state próprio, recebe
// `seleccionadas` e devolve por `onChange` a lista inteira e nova. A escolha
// não pode viver aqui dentro — quem grava a linha é o diálogo do produto, e
// uma cópia local ficava a divergir da linha assim que o servidor devolvesse
// a venda (é o mesmo raciocínio dos totais, que nunca se somam no browser).
//
// Como o PosEntrar, é presentacional em relação ao SEU contentor: enche o
// espaço que lhe derem, nunca fixa alturas nem scroll próprio — quem decide
// isso é o diálogo que o embrulha.
//
// Uma opção escolhida viaja sempre como {id, grupo_id, nome, preco}. O
// servidor só usa `nome` (vai entre parêntesis no título que sai no talão) e
// `preco` (soma ao preço unitário) — ver precos.linha_de_venda; o `id` e o
// `grupo_id` são para este ecrã se orientar.

// --- A semântica dos grupos, DERIVADA -----------------------------------------
//
// Não há campos "obrigatorio" nem "tipo" no servidor, de propósito (ver o
// cabeçalho de faturacao/catalogo.py: seriam uma segunda fonte de verdade
// para a mesma informação). Tudo sai de min_select/max_select:
//   min >= 1   -> obrigatório
//   max === 1  -> escolha única (comporta-se como rádio)
//   max === 0  -> sem limite
// Estas três linhas são a única leitura desses números em todo o ficheiro.

// Um grupo que venha sem os campos, ou com lixo lá dentro, não pode rebentar
// o ecrã do balcão: vale 0, que é o valor mais permissivo dos dois (nem
// obriga, nem limita) — inventar um mínimo era pior do que não ter nenhum.
const inteiroNaoNegativo = (valor) => {
  const n = Number(valor);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
};

const contagem = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;

// O MESMO formato dos outros ecrãs do POS (PosCaixaFechada, PosMenuCaixa,
// PosFecharCaixa) — duas casas sempre, vírgula decimal de PT-PT.
// A formatação de dinheiro vem de `@/lib/pos` e NÃO é escrita aqui: eram oito
// cópias da mesma linha, e as oito transformavam `undefined`/`null`/`NaN` num
// "€ 0,00" perfeitamente legível. Ver `numeroPos` lá.

// O que se pede ao grupo, por palavras e não pelos números crus (o mesmo que
// o backoffice faz em FatPersonalizacoes: quem está ao balcão nunca vê
// "min_select 1 / max_select 3").
const textoDaRegra = (min, max) => {
  if (min === 0 && max === 0) return 'Opcional';
  if (min === 0) return `Escolha até ${max}`;
  if (max === 0) return `Escolha pelo menos ${min}`;
  if (min === max) return `Escolha ${min}`;
  return `Escolha ${min} a ${max}`;
};

// A frase da configuração impossível de satisfazer.
//
// Acontece de verdade: pos_catalogo.py::_grupo_publico filtra as opções
// desactivadas mas NÃO baixa o `min_select` (está lá escrito porquê — baixá-lo
// era o servidor a inventar uma configuração que o gestor não fez). Chega cá,
// portanto, um grupo com min_select 1 e `opcoes: []`.
//
// O sujeito é um argumento porque a mesma frase é dita em dois sítios com
// sujeitos diferentes: no bloco do grupo já há um título com o nome por cima
// ("Este grupo exige…"), mas na lista de erros de `errosDeSelecao` — que quem
// chama mostra longe daqui — a frase tem de dizer de QUAL grupo se trata.
const frasePorSatisfazer = (sujeito, min, disponiveis) => {
  const exigencia = `${sujeito} exige ${contagem(min, 'escolha', 'escolhas')}`;
  if (disponiveis === 0) {
    return `${exigencia} mas não tem nenhuma opção disponível — avise o gestor.`;
  }
  return `${exigencia} mas só tem ${contagem(disponiveis, 'opção disponível', 'opções disponíveis')} — avise o gestor.`;
};

const opcoesDoGrupo = (grupo) => (Array.isArray(grupo?.opcoes) ? grupo.opcoes.filter(Boolean) : []);
const semNulos = (seleccionadas) => (Array.isArray(seleccionadas) ? seleccionadas.filter(Boolean) : []);

// --- As DOSES: o que a repetição na lista quer dizer ---------------------------
//
// A mesma opção DUAS VEZES na lista são duas doses — duas colheres de Nutella,
// cobradas duas vezes (`precos.linha_de_venda` soma cada entrada e
// `_descricao_das_opcoes` agrega-as em "Nutella 2×"). Quem deu esse significado
// à repetição foi o pedido guiado; este painel nasceu antes disso, quando uma
// opção só podia estar na lista uma vez e o toque era um interruptor simétrico.
//
// É desse desencontro que nasceu o defeito que estas funções existem para não
// repetir: com a leitura antiga, tocar numa Nutella de DUAS doses cortava a
// primeira entrada e o botão ficava exactamente igual — aceso, sem número —
// enquanto a linha ficava 0,95 € mais barata numa Fatura Simplificada real,
// sem nada no ecrã a dizê-lo.
const dosesDe = (escolhidas, grupoId, opcaoId) =>
  escolhidas.filter((o) => o.grupo_id === grupoId && o.id === opcaoId).length;

// Quantas OPÇÕES DIFERENTES do grupo estão escolhidas. É este o número que o
// min_select/max_select conta, e nunca as doses: três doses de Nutella não
// podem esgotar um máximo de três (o açaí ficava limitado a três colheres), nem
// duas doses de Nutella podem satisfazer um mínimo de duas escolhas.
const opcoesDiferentesNoGrupo = (escolhidas, grupoId) => {
  const vistas = new Set();
  escolhidas.forEach((o) => { if (o.grupo_id === grupoId) vistas.add(o.id); });
  return vistas.size;
};

// A lista agregada: uma entrada por opção diferente, com as doses contadas,
// pela ORDEM DA PRIMEIRA ESCOLHA — a mesma de `_descricao_das_opcoes`, porque
// agregar não pode reordenar o que o cliente lê no talão. Com a lista crua,
// duas doses da mesma opção desenhavam dois chips iguais (e duas `key` iguais,
// que o React não tolera).
const porDoses = (escolhidas) => {
  const ordem = [];
  const doses = new Map();
  escolhidas.forEach((o) => {
    const chave = `${o.grupo_id}|${o.id}`;
    if (!doses.has(chave)) { ordem.push(o); doses.set(chave, 0); }
    doses.set(chave, doses.get(chave) + 1);
  });
  return ordem.map((o) => ({ opcao: o, doses: doses.get(`${o.grupo_id}|${o.id}`) }));
};

// Um grupo de TEXTO (o "Nome" que se escreve no copo — o `tipo` que o catálogo
// passou a dizer) não tem opções nenhumas: a resposta viaja em
// `respostas_texto` e nunca em `seleccionadas`. Este painel e o
// `errosDeSelecao` só sabem de opções, por isso ignoram-no por inteiro.
//
// Sem esta linha, um "Nome" obrigatório caía na frase da configuração
// impossível ("exige 1 escolha mas não tem nenhuma opção disponível — avise o
// gestor") e DESLIGAVA o Gravar de uma linha que não tinha defeito nenhum: ao
// balcão, essa linha ficava sem desconto, sem quantidade e sem preço, só com o
// "Remover da conta", e a mensagem mandava avisar um gestor que não tinha nada
// para corrigir.
const ehGrupoDeOpcoes = (grupo) => grupo?.tipo !== 'texto';

// --- Os dois exports puros ----------------------------------------------------

/**
 * O que falta (ou sobra) para esta selecção poder ser gravada. Frases em
 * PT-PT, prontas a mostrar; lista vazia = pode gravar.
 *
 * Função pura e sem React de propósito: quem grava a linha precisa de saber
 * isto sem ter o painel desenhado — o botão Gravar do diálogo do produto
 * desliga-se com base nela, e tocar num produto com um grupo obrigatório
 * precisa de saber, ANTES de abrir seja o que for, que há algo por escolher.
 *
 * Duas regras que valem para QUEM QUER QUE a chame, e por isso vivem aqui
 * dentro em vez de em cada chamador (foi de um chamador que não as soube que
 * saiu uma linha por gravar ao balcão):
 *
 * - **conta OPÇÕES DIFERENTES, nunca doses** — repetir a Nutella é pedir
 *   outra colher, não gastar outra escolha;
 * - **um grupo de TEXTO não é da sua conta** — a resposta escrita não viaja
 *   em `seleccionadas` e não há aqui nada que ela possa verificar.
 */
export function errosDeSelecao(grupos, seleccionadas) {
  const escolhidas = semNulos(seleccionadas);
  const erros = [];

  (Array.isArray(grupos) ? grupos : []).forEach((grupo) => {
    if (!grupo || !ehGrupoDeOpcoes(grupo)) return;
    const min = inteiroNaoNegativo(grupo.min_select);
    const max = inteiroNaoNegativo(grupo.max_select);
    const disponiveis = opcoesDoGrupo(grupo).length;
    const quantas = opcoesDiferentesNoGrupo(escolhidas, grupo.id);
    const nome = grupo.nome || 'Este grupo';

    if (min > 0 && quantas < min) {
      // A configuração impossível dá a SUA frase, nunca a genérica: mandar
      // "Escolha pelo menos 1 opção em Toppings" a quem não tem uma única
      // opção para escolher era mandá-la bater com a cabeça na parede até
      // desistir da venda, sem nunca perceber que o catálogo é que está mal.
      erros.push(
        disponiveis < min
          ? frasePorSatisfazer(nome, min, disponiveis)
          : `Escolha pelo menos ${contagem(min, 'opção', 'opções')} em ${nome}.`
      );
    }
    // Repare-se que isto se verifica mesmo com o ecrã a impedir passar do
    // máximo: a selecção também pode vir de uma linha gravada há minutos,
    // com o grupo entretanto mudado no backoffice, e aí é aqui — e só aqui —
    // que alguém dá por isso.
    if (max > 0 && quantas > max) {
      erros.push(`Em ${nome} pode escolher no máximo ${max}.`);
    }
  });

  return erros;
}

/**
 * Se uma opção escolhida é uma INDICAÇÃO DE SERVIÇO — o "Levar", o "Comer
 * aqui" — e não uma escolha que descreve o produto. É por esta pergunta que os
 * ecrãs separam o que se diz uma vez e sem dose ("Levar · Maria") do que leva
 * a dose à frente ("Nutella 2×").
 *
 * A regra é a do TÍTULO DA FATURA (`precos._descricao_das_opcoes`), e vive
 * aqui, numa função só, precisamente para não haver três leituras dela: o
 * interruptor `sai_na_fatura` esconde o que não custa nada, **nunca um euro**.
 * Uma opção COM PREÇO é sempre uma escolha, esteja o interruptor como estiver
 * — o servidor soma-lhe as doses e escreve-as no título ("Extra caramelo 2×"),
 * e um ecrã que a mostrasse uma vez e sem dose escondia da operadora
 * exactamente a dose que o cliente vai pagar. É ela que confere a linha pelo
 * ecrã, e o ecrã não lhe pode dizer menos do que o papel.
 *
 * `!== 0` e não `> 0`, pela mesma razão do servidor: um preço NEGATIVO (um
 * desconto gravado como opção) também mexe no dinheiro da linha.
 *
 * `=== false` e não `!o.sai_na_fatura`: uma linha gravada antes deste campo
 * existir chega sem a chave, e essa vale como "sai na fatura" (é o que o
 * servidor assume) — tratá-la como serviço tirava-lhe a dose.
 */
export const ehIndicacaoDeServico = (opcao) =>
  opcao?.sai_na_fatura === false && (Number(opcao?.preco) || 0) === 0;

/**
 * As escolhas por vírgulas, com as doses ("Nutella 2×, Morango"). String vazia
 * quando não há nenhuma.
 *
 * Mesma ordem e mesmo separador que `precos.linha_de_venda` usa para o título
 * — as repetições AGREGADAS pela ordem da primeira escolha, entre parêntesis a
 * seguir ao nome do produto. Se aqui se ordenasse por outro critério
 * (alfabético, por preço), a operadora lia uma ordem no ecrã e o cliente lia
 * outra no talão, para a mesma linha.
 *
 * A dose só se escreve a partir da SEGUNDA, como no título da fatura (e ao
 * contrário da linha da conta, que a escreve sempre): aqui a lista tem lá
 * dentro as escolhas de serviço, e "Comer aqui 1×" é uma dose de uma coisa que
 * não se serve às colheres — no painel, aliás, essas nem contador têm.
 *
 * Escrever os nomes crus era pior do que qualquer destas escolhas: com duas
 * doses lia-se "Nutella, Nutella" no diálogo do produto e "Nutella 2×" na
 * conta ao lado — a mesma linha dita de duas maneiras, e a repetição de um
 * nome não se conta de relance.
 */
export function resumoDaSelecao(seleccionadas) {
  // Agrega por NOME, e não por opção: é por nome que a fatura agrega
  // (`_descricao_das_opcoes`) e por nome que a conta agrega
  // (`resumoDoPedido`). Um "Morango" dos toppings e um "Morango" da fruta são
  // duas opções diferentes com o mesmo nome — o papel diz "Morango 2×", e
  // dizer aqui "Morango 1×, Morango 1×" era outra vez a mesma linha lida de
  // duas maneiras.
  const doses = new Map();
  semNulos(seleccionadas).forEach((o) => {
    const nome = o.nome ? String(o.nome).trim() : '';
    if (!nome) return;
    doses.set(nome, (doses.get(nome) || 0) + 1);
  });
  return Array.from(doses, ([nome, quantas]) => (quantas === 1 ? nome : `${nome} ${quantas}×`)).join(', ');
}

// --- O painel -----------------------------------------------------------------

function BotaoOpcao({ opcao, doses, alternativa, desligada, onTocar, onRetirar }) {
  const preco = Number(opcao.preco) || 0;
  const escolhida = doses > 0;
  // Num grupo de ALTERNATIVAS (máximo 1) a repetição não quer dizer nada — não
  // há duas doses de "Levar" —, por isso não há contador nem ✕: tocar noutra
  // troca, e tocar na que está escolhida desliga-a.
  const comDoses = escolhida && !alternativa;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onTocar}
        disabled={desligada}
        aria-pressed={escolhida}
        // O contador é `aria-hidden` (é um número solto), por isso as doses
        // têm de vir ditas aqui: quem ouve o botão tem de saber que já lá vão
        // duas colheres antes de tocar noutra.
        aria-label={comDoses ? `${opcao.nome}, ${doses} ${doses === 1 ? 'dose' : 'doses'}` : opcao.nome}
        // O contador e o ✕ ficam por BAIXO, e não ao lado do nome: este painel
        // vive no painel direito da conta, onde cada botão tem uns 110 px de
        // largura — a reservar-lhes espaço à direita, o "Leite condensado"
        // ficava reduzido a duas letras por linha.
        className={`w-full min-h-[4.5rem] rounded-2xl border-2 px-3 py-2.5 ${
          comDoses ? 'pb-11' : ''
        } text-left flex flex-col justify-center gap-0.5 transition-colors active:scale-[0.97] transition-transform ${
          escolhida
            ? 'border-primary bg-primary text-primary-foreground shadow-sm'
            : 'border-border bg-card hover:bg-accent'
        } ${desligada ? 'opacity-40 pointer-events-none' : ''}`}
      >
        <span className="font-medium text-base leading-tight">{opcao.nome}</span>
        {preco > 0 && (
          <span className={`text-sm font-semibold ${escolhida ? 'text-primary-foreground/90' : 'text-muted-foreground'}`}>
            + {euros(preco)} €
          </span>
        )}
      </button>

      {/* O contador e o ✕ ficam FORA do <button>, sobrepostos: um botão dentro
          de outro não é HTML válido e o toque no ✕ acabava a somar mais uma
          dose, que é o contrário do que ele promete. */}
      {comDoses && (
        <div className="absolute inset-x-2 bottom-2 flex items-center justify-between gap-1">
          {/* Aparece à PRIMEIRA dose, e não só à segunda: numa lista onde uns
              nomes têm número e outros não, a operadora lê duas vezes para
              saber se o "Nutella" sem número é uma dose ou nenhuma. */}
          <span
            aria-hidden="true"
            className="h-8 min-w-[2rem] px-1.5 rounded-full bg-primary-foreground text-primary text-sm font-heading font-bold flex items-center justify-center tabular-nums"
          >
            {doses}×
          </span>
          <button
            type="button"
            onClick={onRetirar}
            aria-label={`Retirar ${opcao.nome || 'esta opção'}`}
            className="h-8 w-8 shrink-0 rounded-full bg-primary-foreground text-primary flex items-center justify-center hover:opacity-80 active:scale-95 transition-transform"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}

// Uma opção que a operadora escolheu e que o catálogo já não oferece (o
// gestor desactivou-a, ou desactivou o grupo inteiro, depois de a linha ter
// sido gravada). Continua a contar para o preço da linha, por isso NÃO se
// apaga sozinha nem se esconde: fica à vista, marcada, e com um X para quem
// está ao balcão decidir. Deixá-la cair em silêncio mudava o preço da linha
// sem ninguém pedir.
function OpcaoFantasma({ opcao, doses, onRemover }) {
  const preco = Number(opcao.preco) || 0;
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-dashed border-warning/60 bg-warning/10 pl-3 pr-1.5 py-1.5 text-sm">
      <span className="font-medium">{opcao.nome || 'Opção sem nome'}</span>
      {/* As doses também aqui: uma opção fora do catálogo pode ter sido
          escolhida três vezes, e são as três que continuam a pesar no preço
          desta linha — o chip tinha de o dizer antes de alguém decidir. */}
      <span className="font-heading font-bold tabular-nums">{doses}×</span>
      {preco > 0 && <span className="text-muted-foreground">+ {euros(preco)} € cada</span>}
      <button
        type="button"
        onClick={onRemover}
        aria-label={`Retirar ${opcao.nome || 'esta opção'}`}
        className="h-7 w-7 rounded-full flex items-center justify-center hover:bg-warning/20 active:scale-95 transition-transform"
      >
        <X className="h-4 w-4" />
      </button>
    </span>
  );
}

function Aviso({ children }) {
  return (
    <div className="flex items-start gap-2 rounded-xl bg-warning/10 text-warning p-3 text-sm">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <span>{children}</span>
    </div>
  );
}

export default function PosPersonalizacoes({ grupos, seleccionadas, onChange }) {
  // Os grupos de TEXTO ficam de fora: este painel só sabe de opções (está
  // escrito porquê em `ehGrupoDeOpcoes`).
  const todos = (Array.isArray(grupos) ? grupos : []).filter(Boolean).filter(ehGrupoDeOpcoes);
  const escolhidas = semNulos(seleccionadas);

  // Retira a opção POR INTEIRO, todas as doses de uma vez — é o que o ✕
  // promete, e a única forma de o ecrã não mentir. Cortar só a primeira
  // entrada, como se fazia, deixava a Nutella de duas doses acesa e igualzinha
  // com a linha 0,95 € mais barata.
  const retirar = (opcao) =>
    onChange(escolhidas.filter((o) => !(o.grupo_id === opcao.grupo_id && o.id === opcao.id)));

  const tocar = (grupo, opcao, max) => {
    const nova = {
      id: opcao.id,
      grupo_id: grupo.id,
      nome: opcao.nome,
      // Number(...) aqui e não mais abaixo: o preço da opção soma ao preço
      // unitário no servidor, e uma string "0.95" vinda de um catálogo antigo
      // somava como concatenação em qualquer conta feita no ecrã.
      preco: Number(opcao.preco) || 0,
    };

    if (max === 1) {
      // Tocar na que já está escolhida DESLIGA-A (e todas as entradas dela, se
      // uma linha antiga tiver mais do que uma). Só aqui é que o toque desliga:
      // num grupo de alternativas a repetição não quer dizer dose nenhuma.
      if (dosesDe(escolhidas, grupo.id, opcao.id) > 0) {
        retirar(nova);
        return;
      }
      // Escolha única: a nova entra NO LUGAR da anterior, e não "fora a
      // anterior, a nova ao fim". O título da linha sai com os nomes pela
      // ordem desta lista (precos.linha_de_venda), e corrigir o tamanho
      // passava "Açaí (Grande, Nutella)" a "Açaí (Nutella, Médio)" — a mesma
      // linha a mudar de nome no ecrã e no talão por causa de uma correcção.
      // Se por algum motivo houver mais do que uma do grupo (uma linha
      // gravada antes de o grupo ter passado a escolha única), as restantes
      // caem aqui — é a única forma de a linha voltar a ser gravável.
      const resultado = [];
      let colocada = false;
      escolhidas.forEach((o) => {
        if (o.grupo_id === grupo.id) {
          if (!colocada) { resultado.push(nova); colocada = true; }
          return;
        }
        resultado.push(o);
      });
      if (!colocada) resultado.push(nova);
      onChange(resultado);
      return;
    }

    // Fora das alternativas, cada toque JUNTA UMA DOSE — o mesmo gesto e o
    // mesmo significado que tem no pedido guiado, para o mesmo botão não
    // querer dizer coisas opostas em dois ecrãs do mesmo POS. Quem retira é o
    // ✕ do canto, e é por isso que ele existe.
    onChange([...escolhidas, nova]);
  };

  // Um produto pode apontar para um grupo que o catálogo já não devolve
  // (grupo desactivado): o componente recebe simplesmente menos grupos. As
  // escolhas órfãs desses grupos ficam sem bloco onde aparecer, e é isso que
  // este apanhado recolhe — para irem para o fim, à vista, em vez de
  // desaparecerem do ecrã continuando a pesar no preço.
  const idsDeGrupo = new Set(todos.map((g) => g.id));
  const semGrupo = escolhidas.filter((o) => !idsDeGrupo.has(o.grupo_id));

  if (todos.length === 0 && semGrupo.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        {/* "não tem opções para escolher", e não "não tem personalizações":
            um produto pode ter só um grupo de texto (o Nome), e esse existe —
            só não é deste painel, que não recebe as respostas escritas. */}
        Este produto não tem opções para escolher.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {todos.map((grupo) => {
        const min = inteiroNaoNegativo(grupo.min_select);
        const max = inteiroNaoNegativo(grupo.max_select);
        const opcoes = opcoesDoGrupo(grupo);
        const doGrupo = escolhidas.filter((o) => o.grupo_id === grupo.id);
        // OPÇÕES DIFERENTES escolhidas neste grupo — nunca doses (ver
        // `opcoesDiferentesNoGrupo`). Era daqui que saía o "4 de 2" a olhar
        // para Morango 3× + Kiwi 1×: quatro doses de duas frutas num grupo que
        // deixa escolher duas frutas.
        const diferentes = opcoesDiferentesNoGrupo(escolhidas, grupo.id);
        // Escolhidas cuja opção já não está no grupo (foi desactivada depois
        // de a linha ter sido gravada). Contam para o contador do grupo — são
        // escolhas que a linha tem mesmo — mas aparecem à parte, porque não
        // há botão nenhum para as destacar.
        const idsDisponiveis = new Set(opcoes.map((o) => o.id));
        const fantasmas = porDoses(doGrupo.filter((o) => !idsDisponiveis.has(o.id)));
        const noMaximo = max > 0 && diferentes >= max;
        const porSatisfazer = min > opcoes.length;

        return (
          <div key={grupo.id} className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div className="min-w-0">
                <h4 className="font-heading font-bold text-lg leading-tight truncate">{grupo.nome}</h4>
                <p className="text-xs text-muted-foreground mt-0.5">{textoDaRegra(min, max)}</p>
              </div>
              {max > 0 && (
                <span className="text-xs text-muted-foreground tabular-nums shrink-0">
                  {diferentes} de {max}
                </span>
              )}
            </div>

            {/* O aviso aparece SEMPRE que o mínimo é maior do que as opções
                que sobraram, mesmo quando as escolhas já gravadas o cumprem:
                quem tem de saber disto é o gestor, e a única pessoa que lho
                pode dizer é quem está a olhar para este ecrã. Só que aí não
                bloqueia a gravação — ver errosDeSelecao. */}
            {porSatisfazer && <Aviso>{frasePorSatisfazer('Este grupo', min, opcoes.length)}</Aviso>}

            {opcoes.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                {opcoes.map((opcao) => {
                  const doses = dosesDe(escolhidas, grupo.id, opcao.id);
                  return (
                    <BotaoOpcao
                      key={opcao.id}
                      opcao={opcao}
                      doses={doses}
                      alternativa={max === 1}
                      // Numa escolha única nunca se desliga nada: tocar noutra
                      // troca, e é assim que se corrige um engano. Só um grupo
                      // com máximo de 2 ou mais é que fecha a porta ao passar
                      // do máximo — e diz logo por baixo como se abre. Uma
                      // opção JÁ escolhida nunca se desliga: no máximo, é a
                      // única em que ainda se pode juntar outra dose ou tocar
                      // no ✕ para a retirar.
                      desligada={max > 1 && noMaximo && doses === 0}
                      onTocar={() => tocar(grupo, opcao, max)}
                      onRetirar={() => retirar({ grupo_id: grupo.id, id: opcao.id })}
                    />
                  );
                })}
              </div>
            ) : (
              !porSatisfazer && (
                <p className="text-sm text-muted-foreground">Sem opções disponíveis neste grupo.</p>
              )
            )}

            {/* O gesto tem de estar escrito: um toque numa opção já acesa
                junta OUTRA dose (e cobra-a outra vez), e ninguém adivinha que
                é o ✕ que a retira. Nas alternativas não se diz nada — lá o
                toque troca, e é o que se espera de dois botões que são
                "ou um, ou o outro". */}
            {opcoes.length > 0 && max !== 1 && (
              <p className="text-xs text-muted-foreground">
                Toque para juntar outra dose · ✕ retira a opção inteira.
              </p>
            )}

            {max > 1 && noMaximo && (
              <p className="text-xs text-muted-foreground">
                Máximo atingido — retire uma para trocar.
              </p>
            )}

            {fantasmas.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">
                  Já escolhidas mas fora do catálogo — continuam a contar para o preço desta linha.
                </p>
                <div className="flex flex-wrap gap-2">
                  {fantasmas.map(({ opcao, doses }) => (
                    <OpcaoFantasma
                      key={`${opcao.grupo_id}-${opcao.id}`}
                      opcao={opcao}
                      doses={doses}
                      onRemover={() => retirar(opcao)}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {semGrupo.length > 0 && (
        <div className="space-y-2 border-t pt-4">
          <h4 className="font-heading font-bold text-base">Personalizações fora do catálogo</h4>
          <p className="text-xs text-muted-foreground">
            O grupo destas opções já não está activo. Continuam a contar para o preço desta linha até
            serem retiradas.
          </p>
          <div className="flex flex-wrap gap-2">
            {porDoses(semGrupo).map(({ opcao, doses }) => (
              <OpcaoFantasma
                key={`${opcao.grupo_id}-${opcao.id}`}
                opcao={opcao}
                doses={doses}
                onRemover={() => retirar(opcao)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
