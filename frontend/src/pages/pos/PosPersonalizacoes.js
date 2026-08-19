import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

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
const euros = (valor) =>
  (Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

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

// --- Os dois exports puros ----------------------------------------------------

/**
 * O que falta (ou sobra) para esta selecção poder ser gravada. Frases em
 * PT-PT, prontas a mostrar; lista vazia = pode gravar.
 *
 * Função pura e sem React de propósito: quem grava a linha precisa de saber
 * isto sem ter o painel desenhado — o botão Gravar do diálogo do produto
 * desliga-se com base nela, e tocar num produto com um grupo obrigatório
 * precisa de saber, ANTES de abrir seja o que for, que há algo por escolher.
 */
export function errosDeSelecao(grupos, seleccionadas) {
  const escolhidas = semNulos(seleccionadas);
  const erros = [];

  (Array.isArray(grupos) ? grupos : []).forEach((grupo) => {
    if (!grupo) return;
    const min = inteiroNaoNegativo(grupo.min_select);
    const max = inteiroNaoNegativo(grupo.max_select);
    const disponiveis = opcoesDoGrupo(grupo).length;
    const quantas = escolhidas.filter((o) => o.grupo_id === grupo.id).length;
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
 * Os nomes por vírgulas, para a linha da conta ("Nutella, Morango"). String
 * vazia quando não há nenhuma.
 *
 * Mesma ordem e mesmo separador que `precos.linha_de_venda` usa para o título
 * — ", ".join(nomes) entre parêntesis a seguir ao nome do produto. Se aqui se
 * ordenasse por outro critério (alfabético, por preço), a operadora lia uma
 * ordem no ecrã e o cliente lia outra no talão, para a mesma linha.
 */
export function resumoDaSelecao(seleccionadas) {
  return semNulos(seleccionadas)
    .map((o) => (o.nome ? String(o.nome).trim() : ''))
    .filter(Boolean)
    .join(', ');
}

// --- O painel -----------------------------------------------------------------

function BotaoOpcao({ opcao, escolhida, desligada, onTocar }) {
  const preco = Number(opcao.preco) || 0;
  return (
    <button
      type="button"
      onClick={onTocar}
      disabled={desligada}
      aria-pressed={escolhida}
      className={`min-h-[4.5rem] rounded-2xl border-2 px-3 py-2.5 text-left flex flex-col justify-center gap-0.5 transition-colors active:scale-[0.97] transition-transform ${
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
  );
}

// Uma opção que a operadora escolheu e que o catálogo já não oferece (o
// gestor desactivou-a, ou desactivou o grupo inteiro, depois de a linha ter
// sido gravada). Continua a contar para o preço da linha, por isso NÃO se
// apaga sozinha nem se esconde: fica à vista, marcada, e com um X para quem
// está ao balcão decidir. Deixá-la cair em silêncio mudava o preço da linha
// sem ninguém pedir.
function OpcaoFantasma({ opcao, onRemover }) {
  const preco = Number(opcao.preco) || 0;
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-dashed border-warning/60 bg-warning/10 pl-3 pr-1.5 py-1.5 text-sm">
      <span className="font-medium">{opcao.nome || 'Opção sem nome'}</span>
      {preco > 0 && <span className="text-muted-foreground">+ {euros(preco)} €</span>}
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
  const todos = (Array.isArray(grupos) ? grupos : []).filter(Boolean);
  const escolhidas = semNulos(seleccionadas);

  const estaEscolhida = (grupoId, opcaoId) =>
    escolhidas.some((o) => o.grupo_id === grupoId && o.id === opcaoId);

  const remover = (opcao) => {
    const indice = escolhidas.findIndex((o) => o.grupo_id === opcao.grupo_id && o.id === opcao.id);
    if (indice < 0) return;
    onChange(escolhidas.filter((_, i) => i !== indice));
  };

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

    if (estaEscolhida(grupo.id, opcao.id)) {
      remover(nova);
      return;
    }

    if (max === 1) {
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
        Este produto não tem personalizações.
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
        // Escolhidas cuja opção já não está no grupo (foi desactivada depois
        // de a linha ter sido gravada). Contam para o contador do grupo — são
        // escolhas que a linha tem mesmo — mas aparecem à parte, porque não
        // há botão nenhum para as destacar.
        const idsDisponiveis = new Set(opcoes.map((o) => o.id));
        const fantasmas = doGrupo.filter((o) => !idsDisponiveis.has(o.id));
        const noMaximo = max > 0 && doGrupo.length >= max;
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
                  {doGrupo.length} de {max}
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
                {opcoes.map((opcao) => (
                  <BotaoOpcao
                    key={opcao.id}
                    opcao={opcao}
                    escolhida={estaEscolhida(grupo.id, opcao.id)}
                    // Numa escolha única nunca se desliga nada: tocar noutra
                    // troca, e é assim que se corrige um engano. Só um grupo
                    // com máximo de 2 ou mais é que fecha a porta ao passar
                    // do máximo — e diz logo por baixo como se abre.
                    desligada={max > 1 && noMaximo && !estaEscolhida(grupo.id, opcao.id)}
                    onTocar={() => tocar(grupo, opcao, max)}
                  />
                ))}
              </div>
            ) : (
              !porSatisfazer && (
                <p className="text-sm text-muted-foreground">Sem opções disponíveis neste grupo.</p>
              )
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
                  {fantasmas.map((o) => (
                    <OpcaoFantasma key={`${o.grupo_id}-${o.id}`} opcao={o} onRemover={() => remover(o)} />
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
            {semGrupo.map((o) => (
              <OpcaoFantasma key={`${o.grupo_id}-${o.id}`} opcao={o} onRemover={() => remover(o)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
