import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { errosDeSelecao } from './PosPersonalizacoes';

// O pedido guiado do POS: o pop-up que se abre ao tocar num açaí e que conduz
// o pedido do cliente — levar ou comer aqui, os toppings com as doses, o nome
// que se escreve no copo. Só depois de Gravar é que a linha vai para a conta.
//
// A ideia de que tudo o resto decorre: **isto não é um ecrã fixo**. É a
// sequência dos GRUPOS DE PERSONALIZAÇÃO do próprio produto, um passo por
// grupo, pela ordem em que o produto os declara. Quais os artigos que abrem
// esta conversa decide-se pela atribuição dos grupos no backoffice — não por
// uma marca no produto, nem por uma lista aqui dentro. Um artigo sem grupos
// nenhuns continua a ir para a conta com um único toque.
//
// **Flutuante e ao centro** (Dialog), e não o painel direito onde vive o
// PosDialogoProduto: a grelha e a conta ficam à vista por trás, e a operadora
// vê o que já picou enquanto monta o pedido.
//
// Nada entra na conta antes do Gravar — fechar a meio não deixa rasto.
//
// Este ficheiro não soma dinheiro nenhum: devolve `opcoes` e
// `respostas_texto` a quem grava, e é o servidor que faz as contas (o preço
// de cada dose entra no preço unitário em `precos.linha_de_venda`).

// Quanto tempo o dedo tem de ficar em cima para apagar uma opção por inteiro.
// Dois segundos é longo o bastante para não acontecer por engano com o polegar
// apressado, e curto o bastante para se aguentar — mas só funciona porque o
// botão MOSTRA o tempo a correr (a barra que enche por baixo). Sem sinal
// nenhum, solta-se antes do fim e conclui-se que o gesto não existe.
const MS_ATE_APAGAR = 2000;

// O limite dos caracteres do `RespostaTexto.texto` (venda.py). Está aqui para
// o campo não deixar escrever o que o servidor vai recusar com um 422 depois
// de a operadora carregar em Gravar.
const MAX_TEXTO = 120;

// O MESMO formato dos outros ecrãs do POS: duas casas sempre, vírgula decimal
// de PT-PT.
const euros = (valor) =>
  (Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// A mesma leitura permissiva do `PosPersonalizacoes` (é lá que está escrito
// porquê): um grupo sem os campos, ou com lixo lá dentro, vale 0 — nem obriga,
// nem limita. Está repetida aqui porque a de lá é privada ao ficheiro, não
// porque a regra seja outra.
const limite = (valor) => {
  const n = Number(valor);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
};

// Tudo o que não for `texto` é uma lista de opções. Um grupo vindo de um
// servidor anterior à Task 4 chega sem `tipo` (o catálogo põe-lhe "opcoes"), e
// um tipo inventado no futuro não pode deixar a operadora a olhar para um
// passo em branco a meio de um pedido.
const tipoDoGrupo = (grupo) => (grupo?.tipo === 'texto' ? 'texto' : 'opcoes');

const opcoesDoGrupo = (grupo) => (Array.isArray(grupo?.opcoes) ? grupo.opcoes.filter(Boolean) : []);

// Uma entrada por opção DIFERENTE, pela ordem da primeira escolha — é o que o
// contador do máximo deste ecrã tem de contar, porque o `min_select`/
// `max_select` de um grupo conta OPÇÕES, nunca doses. Nos toppings do açaí não
// há máximo nenhum e o cliente pede o que quiser; três doses de Nutella não
// podem esgotar um máximo de três, nem duas doses de Nutella podem satisfazer
// um mínimo de duas escolhas.
//
// Ao `errosDeSelecao` dá-se a lista CRUA: essa regra passou a viver lá dentro,
// que é onde tinha de estar. Enquanto foi este ecrã a tirar-lhe as repetições
// antes de lha entregar, o painel de sempre — que recebe a mesma linha quando
// se vai corrigi-la — continuou a contar doses e recusava-a com "Em Fruta pode
// escolher no máximo 2." a olhar para duas frutas.
const umaPorOpcao = (escolhidas) => {
  const vistas = new Set();
  const resultado = [];
  (Array.isArray(escolhidas) ? escolhidas : []).forEach((o) => {
    if (!o) return;
    const chave = `${o.grupo_id}|${o.id}`;
    if (vistas.has(chave)) return;
    vistas.add(chave);
    resultado.push(o);
  });
  return resultado;
};

const dosesDe = (escolhidas, grupoId, opcaoId) =>
  escolhidas.filter((o) => o && o.grupo_id === grupoId && o.id === opcaoId).length;

const diferentesNoGrupo = (escolhidas, grupoId) =>
  umaPorOpcao(escolhidas).filter((o) => o.grupo_id === grupoId).length;

// O que se pede a este passo, por palavras. Não se reaproveita o texto do
// `PosPersonalizacoes` porque aqui a frase tem de dizer a diferença entre
// DOSES e OPÇÕES: "Escolha até 3" num ecrã onde cada toque junta uma dose
// lia-se como "três colheres de Nutella", que é o contrário do que acontece.
const regraDoPasso = (grupo, tipo, min, max) => {
  if (tipo === 'texto') return min > 0 ? 'Resposta obrigatória.' : 'Pode deixar em branco.';
  // Máximo de 1 é um grupo de ALTERNATIVAS (o "Consumir na loja"): tocar
  // noutra troca, não junta.
  if (max === 1) return min > 0 ? 'Escolha uma opção.' : 'Escolha uma opção, ou nenhuma.';
  if (min > 0 && max > 0) return `De ${min} a ${max} opções diferentes — cada toque junta uma dose.`;
  if (min > 0) {
    return `Pelo menos ${min === 1 ? 'uma opção' : `${min} opções diferentes`} — cada toque junta uma dose.`;
  }
  if (max > 0) return `Até ${max} opções diferentes — cada toque junta uma dose.`;
  return 'Escolha à vontade — cada toque junta uma dose.';
};

/**
 * O pedido de uma linha JÁ GRAVADA, em duas frases prontas a mostrar por
 * baixo do nome do produto na conta: `Levar · Maria` e
 * `Nutella 2× · Leite condensado 1×`. É o que a operadora confere com o
 * cliente antes de finalizar.
 *
 * A divisão é a MESMA de `talao.pedido_da_cozinha`: o que vem de um grupo com
 * `sai_na_fatura` desligado são indicações de serviço (Levar / Comer aqui),
 * dizem-se uma vez e sem dose; o resto são as escolhas que descrevem o
 * produto, e essas levam a dose à frente. O ecrã e o papel da cozinha lêem a
 * linha pela mesma regra de propósito — é com esse papel que ela confere.
 *
 * A dose aparece SEMPRE, mesmo a `1×`, e é diferente do título da fatura (que
 * omite o `1×`): aqui o número é para se conferir de relance quantas colheres
 * foram pedidas, e uma lista onde só alguns nomes têm número obriga a ler o
 * resto duas vezes.
 */
export function resumoDoPedido(linha) {
  const opcoes = (Array.isArray(linha?.opcoes) ? linha.opcoes : []).filter(Boolean);
  const respostas = (Array.isArray(linha?.respostas_texto) ? linha.respostas_texto : []).filter(Boolean);

  const servico = [];
  opcoes.forEach((o) => {
    // `=== false` e não `!o.sai_na_fatura`: uma linha gravada antes destes
    // campos existirem chega sem a chave, e essa vale como "sai na fatura"
    // (é o que o servidor assume) — tratá-la como serviço tirava-lhe a dose.
    if (o.sai_na_fatura !== false || !o.nome) return;
    const nome = String(o.nome);
    if (!servico.includes(nome)) servico.push(nome);
  });
  respostas.forEach((r) => {
    const texto = String(r.texto || '').trim();
    if (texto) servico.push(texto);
  });

  const contagem = new Map();
  opcoes.forEach((o) => {
    if (o.sai_na_fatura === false || !o.nome) return;
    const nome = String(o.nome);
    contagem.set(nome, (contagem.get(nome) || 0) + 1);
  });

  return {
    servico: servico.join(' · '),
    escolhas: Array.from(contagem, ([nome, quantas]) => `${nome} ${quantas}×`).join(' · '),
  };
}

// --- O botão de uma opção -----------------------------------------------------

function BotaoOpcao({ opcao, doses, alternativa, desligado, onDose, onApagar }) {
  const [aApagar, setAApagar] = useState(false);
  const relogio = useRef(null);
  // O `click` chega SEMPRE depois do `pointerup`, mesmo quando o carregar
  // longo já apagou a opção. Sem esta bandeira, apagar as duas doses de
  // Nutella deixava-a logo outra vez com uma — o gesto desfazia-se a si
  // próprio e ninguém percebia porquê.
  const ignorarClique = useRef(false);

  useEffect(() => () => { if (relogio.current) clearTimeout(relogio.current); }, []);

  const pararRelogio = useCallback(() => {
    if (relogio.current) {
      clearTimeout(relogio.current);
      relogio.current = null;
    }
    setAApagar(false);
  }, []);

  const comecar = () => {
    ignorarClique.current = false;
    // Sem doses não há nada para apagar, e a barra a encher prometia uma
    // acção que não ia acontecer.
    if (desligado || doses === 0) return;
    setAApagar(true);
    relogio.current = setTimeout(() => {
      relogio.current = null;
      setAApagar(false);
      ignorarClique.current = true;
      onApagar();
    }, MS_ATE_APAGAR);
  };

  const clicar = () => {
    if (ignorarClique.current) {
      ignorarClique.current = false;
      return;
    }
    onDose();
  };

  const preco = Number(opcao.preco) || 0;
  const escolhida = doses > 0;

  return (
    <button
      type="button"
      onClick={clicar}
      onPointerDown={comecar}
      onPointerUp={pararRelogio}
      onPointerLeave={pararRelogio}
      onPointerCancel={pararRelogio}
      // O carregar longo, no telemóvel e no tablet, abre o menu de contexto e
      // agarra o texto do botão — e é sobre esse menu que o dedo fica os dois
      // segundos, sem ver barra nenhuma.
      onContextMenu={(e) => e.preventDefault()}
      disabled={desligado}
      aria-pressed={escolhida}
      aria-label={escolhida ? `${opcao.nome}, ${doses} ${doses === 1 ? 'dose' : 'doses'}` : opcao.nome}
      style={{ WebkitTouchCallout: 'none' }}
      className={`relative overflow-hidden select-none touch-manipulation min-h-[5rem] rounded-2xl border-2 px-3 py-2.5 text-left flex flex-col justify-center gap-0.5 transition-colors transition-transform ${
        aApagar ? 'scale-[0.97]' : 'active:scale-[0.97]'
      } ${
        escolhida
          ? 'border-primary bg-primary text-primary-foreground shadow-sm'
          : 'border-border bg-card hover:bg-accent'
      } ${desligado ? 'opacity-40 pointer-events-none' : ''}`}
    >
      <span className="font-medium text-base leading-tight pr-9">{opcao.nome}</span>
      {preco > 0 && (
        <span className={`text-sm font-semibold ${escolhida ? 'text-primary-foreground/90' : 'text-muted-foreground'}`}>
          + {euros(preco)} €
        </span>
      )}

      {/* O contador aparece à primeira dose, e não só à segunda: numa lista
          onde uns nomes têm número e outros não, a operadora tem de ler duas
          vezes para saber se o "Nutella" sem número é uma dose ou nenhuma. */}
      {escolhida && !alternativa && (
        <span className="absolute right-2 top-2 h-7 min-w-[1.75rem] px-1.5 rounded-full bg-primary-foreground text-primary text-sm font-heading font-bold flex items-center justify-center tabular-nums">
          {doses}×
        </span>
      )}

      {/* O carregar longo A ACONTECER. Sem isto o gesto é invisível: solta-se
          antes dos 2 s e conclui-se que não funciona. A largura anima por
          transição (e não por keyframes) para o mesmo elemento servir os dois
          sentidos — enche em 2 s ao carregar, esvazia num instante ao soltar. */}
      <span
        aria-hidden="true"
        className="absolute inset-x-0 bottom-0 h-2 bg-destructive origin-left"
        style={{
          transform: `scaleX(${aApagar ? 1 : 0})`,
          transitionProperty: 'transform',
          transitionTimingFunction: 'linear',
          transitionDuration: aApagar ? `${MS_ATE_APAGAR}ms` : '120ms',
        }}
      />
    </button>
  );
}

function BlocoErros({ erros }) {
  if (erros.length === 0) return null;
  return (
    <div className="flex items-start gap-2 rounded-xl bg-destructive/10 text-destructive p-3 text-sm">
      <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
      <div className="space-y-0.5">
        {erros.map((erro, i) => <p key={`${i}-${erro}`}>{erro}</p>)}
      </div>
    </div>
  );
}

// --- O pop-up -----------------------------------------------------------------

export default function PosPedidoGuiado({ produto, grupos, linha, aGravar, onGravar, onFechar }) {
  const passos = useMemo(() => (Array.isArray(grupos) ? grupos.filter(Boolean) : []), [grupos]);
  const [passo, setPasso] = useState(0);

  // As escolhas viajam numa lista SIMPLES em que a repetição é a dose — é
  // assim que o servidor as soma (`precos.linha_de_venda`) e que o título da
  // fatura as agrega. Não há aqui nenhum {opcao, quantidade}: seria uma
  // segunda forma de dizer a mesma coisa, e a conversão entre as duas é
  // exactamente onde uma dose se perde.
  //
  // A corrigir uma linha, as escolhas de um grupo que o catálogo já não
  // devolve (o gestor desactivou-o entretanto) não têm passo nenhum onde
  // aparecer — mas ficam aqui e voltam a ser gravadas tal e qual. Continuam a
  // somar ao preço unitário no servidor, e deixá-las cair em silêncio mudava
  // o preço da linha sem ninguém pedir (é a mesma regra das "fora do
  // catálogo" do PosPersonalizacoes).
  const [opcoes, setOpcoes] = useState(() => (Array.isArray(linha?.opcoes) ? linha.opcoes.filter(Boolean) : []));
  // As respostas escritas TAL COMO VIERAM da linha. Guarda-se a lista, e não
  // só o texto de cada uma, por duas razões que ao balcão são a mesma:
  //
  // 1. uma resposta cujo grupo o catálogo já não devolve como grupo de texto
  //    (o gestor desactivou-o, ou trocou-lhe o tipo) não tem passo nenhum
  //    onde apareça — mas volta a ser gravada tal e qual, como as opções
  //    órfãs aqui em cima. O pedido reenvia a lista INTEIRA e o servidor
  //    grava esse delta em cru: reconstruí-la só a partir dos grupos de hoje
  //    apagava a MARIA do talão da cozinha porque a operadora foi juntar uma
  //    dose de Nutella, e sem uma palavra no ecrã;
  // 2. a ORDEM é a que a linha tinha: o talão põe no copo a PRIMEIRA resposta
  //    não vazia (`talao._nome_no_copo`), por isso reordenar a lista ao
  //    corrigir uma linha trocava o nome que vai no copo — a mesma razão por
  //    que uma alternativa entra no lugar da anterior, e não no fim.
  const respostasLidas = useMemo(
    () => (Array.isArray(linha?.respostas_texto) ? linha.respostas_texto.filter((r) => r && r.grupo_id) : []),
    [linha],
  );

  const [textos, setTextos] = useState(() => {
    const inicial = {};
    (Array.isArray(linha?.respostas_texto) ? linha.respostas_texto : []).forEach((r) => {
      if (r && r.grupo_id) inicial[r.grupo_id] = r.texto || '';
    });
    return inicial;
  });

  // Se este passo já pode queixar-se. Um passo obrigatório abria com a queixa
  // em vermelho ANTES de a operadora fazer o que quer que fosse — o ecrã a
  // acusá-la de um engano que ela ainda não teve tempo de cometer. A regra do
  // passo ("Escolha uma opção.") está no cabeçalho desde o início; o vermelho
  // só aparece depois de ela mexer, ou de tentar seguir em frente.
  const [avisar, setAvisar] = useState(false);

  const indice = Math.min(passo, Math.max(passos.length - 1, 0));
  const grupo = passos[indice];
  const tipo = tipoDoGrupo(grupo);
  const min = limite(grupo?.min_select);
  const max = limite(grupo?.max_select);
  const ultimo = indice >= passos.length - 1;

  const campo = useRef(null);
  useEffect(() => {
    // Cada passo começa calado (ver `avisar`) — incluindo um passo a que se
    // VOLTA com o Anterior, que não é um passo em que ela acabou de falhar.
    setAvisar(false);
    // O passo do nome abre com o cursor lá dentro: no tablet é o que faz
    // subir o teclado, e no PC do balcão é o que deixa escrever sem tirar a
    // mão do sítio. Corre a cada passo porque o campo não é remontado.
    if (tipo === 'texto' && campo.current) campo.current.focus();
  }, [indice, tipo]);

  const juntarDose = (opcao) => {
    setAvisar(true);
    const nova = {
      id: opcao.id,
      grupo_id: grupo.id,
      nome: opcao.nome,
      // Number(...) aqui, como no PosPersonalizacoes: um "0.95" em texto,
      // vindo de um catálogo antigo, somava como concatenação.
      preco: Number(opcao.preco) || 0,
    };

    if (max === 1) {
      // Um grupo de máximo 1 são ALTERNATIVAS, não doses: escolher "Comer
      // aqui" substitui "Levar" em vez de somar. Sem esta distinção, ou o
      // açaí ficava limitado a três colheres, ou o serviço deixava escolher
      // os dois ao mesmo tempo — os dois estão errados.
      //
      // A nova entra NO LUGAR da anterior (e não "fora a anterior, a nova ao
      // fim") pela razão de sempre: o título da linha sai com os nomes pela
      // ordem desta lista, e corrigir uma escolha não pode reordenar o que o
      // cliente lê no talão.
      setOpcoes((atuais) => {
        const resultado = [];
        let colocada = false;
        atuais.forEach((o) => {
          if (o.grupo_id === grupo.id) {
            if (!colocada) { resultado.push(nova); colocada = true; }
            return;
          }
          resultado.push(o);
        });
        if (!colocada) resultado.push(nova);
        return resultado;
      });
      return;
    }

    setOpcoes((atuais) => [...atuais, nova]);
  };

  const apagarOpcao = (opcao) => {
    setAvisar(true);
    // Apaga a opção POR INTEIRO, todas as doses de uma vez: é o que o gesto
    // promete ("carregue 2 segundos para apagar"), e tirar uma dose de cada
    // vez obrigava a três carregares de dois segundos para desfazer um
    // engano.
    setOpcoes((atuais) => atuais.filter((o) => !(o.grupo_id === grupo.id && o.id === opcao.id)));
  };

  const errosDoPasso = useMemo(() => {
    if (!grupo) return [];
    if (tipoDoGrupo(grupo) === 'texto') {
      // Um grupo de texto tem a SUA frase, dita aqui: o `errosDeSelecao` só
      // sabe de opções e um grupo de texto não tem nenhuma, por isso ignora-o
      // (é o que o impede de dizer "não tem nenhuma opção disponível — avise o
      // gestor" a um Nome obrigatório que está ali à espera de ser escrito) —
      // mas ignorar não é verificar, e o mínimo do Nome tem de valer.
      const escrito = String(textos[grupo.id] || '').trim();
      if (limite(grupo.min_select) > 0 && !escrito) {
        return [`Falta preencher ${grupo.nome || 'esta resposta'}.`];
      }
      return [];
    }
    return errosDeSelecao([grupo], opcoes);
  }, [grupo, opcoes, textos]);

  const podeAvancar = errosDoPasso.length === 0;

  const gravar = () => {
    if (!podeAvancar || aGravar) return;

    // A resposta de um grupo QUE TEM PASSO sai do campo — é o que a operadora
    // acabou de escrever (ou de limpar).
    const doPasso = (g) => ({
      grupo_id: g.id,
      // Um retrato, como o `produto_nome` da linha: o talão da cozinha
      // tem de se ler daqui a um mês sem ir buscar o grupo, que pode ter
      // mudado de nome ou desaparecido.
      nome_grupo: g.nome || null,
      texto: String(textos[g.id] || '').trim(),
    });

    const comPasso = new Map();
    passos.forEach((g) => {
      if (g && g.id && tipoDoGrupo(g) === 'texto') comPasso.set(g.id, g);
    });

    // A lista sai COMPLETA: primeiro o que a linha trazia, cada resposta no
    // seu lugar, e só depois os passos que a linha ainda não tinha
    // respondido. O que não tem passo volta tal e qual — este ecrã não o
    // mostrou, logo não pode ter sido a operadora a mudá-lo.
    const respostas = [];
    const vistos = new Set();
    respostasLidas.forEach((r) => {
      // Uma linha antiga com duas respostas ao mesmo grupo: fica a primeira.
      // Uma resposta por grupo é o que este ecrã sabe escrever, e mandar a
      // editada duas vezes era pior do que a segunda cópia que já lá estava.
      if (vistos.has(r.grupo_id)) return;
      vistos.add(r.grupo_id);
      const grupoDela = comPasso.get(r.grupo_id);
      if (grupoDela) { respostas.push(doPasso(grupoDela)); return; }
      // Órfã: volta com o mesmo texto, normalizada aos três campos do
      // `RespostaTexto` (venda.py) e ao mesmo `trim` das outras — um campo a
      // mais, ou um `texto: null` de um servidor antigo, não podem rebentar
      // em 422 uma gravação que só queria juntar uma dose de Nutella.
      respostas.push({
        grupo_id: r.grupo_id,
        nome_grupo: r.nome_grupo || null,
        texto: String(r.texto == null ? '' : r.texto).trim(),
      });
    });
    passos.forEach((g) => {
      if (comPasso.has(g?.id) && !vistos.has(g.id)) { vistos.add(g.id); respostas.push(doPasso(g)); }
    });

    onGravar({
      opcoes,
      // Uma resposta em branco NÃO viaja. O pedido reenvia sempre a lista
      // inteira, por isso deixá-la de fora é precisamente o que apaga um nome
      // que a operadora limpou ao corrigir a linha; e gravar `texto: ""` era
      // deixar no talão da cozinha uma resposta que ninguém deu.
      respostas_texto: respostas.filter((r) => r.texto !== ''),
    });
  };

  const seguinte = () => {
    // O botão fica VIVO mesmo com o passo por satisfazer, e é o toque que
    // revela o que falta: um botão apagado sem uma palavra ao lado lê-se como
    // avaria do ecrã, e ao balcão isso são dois minutos a carregar mais
    // vezes no mesmo sítio com o cliente à frente.
    if (!podeAvancar) { setAvisar(true); return; }
    if (ultimo) { gravar(); return; }
    setPasso(indice + 1);
  };

  // Sem grupos não há conversa nenhuma para conduzir — quem chama só abre
  // isto com grupos, mas um pop-up vazio e sem saída é o pior fim possível
  // para um produto mal configurado.
  if (!grupo) return null;

  const opcoesVisiveis = opcoesDoGrupo(grupo);
  const escolhidasNoGrupo = diferentesNoGrupo(opcoes, grupo.id);
  const noMaximo = max > 1 && escolhidasNoGrupo >= max;

  return (
    <Dialog
      open
      onOpenChange={(aberto) => {
        // A gravar não se fecha: o pedido está a caminho do servidor e fechar
        // aqui deixava a operadora sem saber se a linha entrou.
        if (!aberto && !aGravar) onFechar();
      }}
    >
      <DialogContent className="sm:max-w-2xl p-0 gap-0 max-h-[92vh] flex flex-col">
        <DialogHeader className="p-4 pr-12 border-b shrink-0 space-y-1">
          <p className="text-xs text-muted-foreground truncate">
            {(linha ? linha.produto_nome || produto?.nome : produto?.nome) || 'Produto'}
          </p>
          <div className="flex items-baseline justify-between gap-3">
            <DialogTitle className="font-heading font-bold text-2xl leading-tight truncate">
              {grupo.nome || 'Personalização'}
            </DialogTitle>
            <span className="text-sm text-muted-foreground tabular-nums shrink-0">
              {indice + 1} de {passos.length}
            </span>
          </div>
          <DialogDescription className="text-sm">{regraDoPasso(grupo, tipo, min, max)}</DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
          {tipo === 'texto' ? (
            <div className="space-y-2">
              <label htmlFor="pedido-guiado-texto" className="text-sm font-medium">
                {grupo.nome || 'Resposta'}
              </label>
              {/* O `md:text-2xl` não é decoração: o `md:text-sm` que o Input
                  traz de base ganhava ao `text-2xl` no ecrã do balcão (é uma
                  media query, não um conflito que o twMerge resolva), e o nome
                  do cliente ficava em letra miúda exactamente no tamanho de
                  ecrã onde este POS corre. */}
              <Input
                id="pedido-guiado-texto"
                ref={campo}
                value={textos[grupo.id] || ''}
                onChange={(e) => {
                  setAvisar(true);
                  setTextos((atuais) => ({ ...atuais, [grupo.id]: e.target.value }));
                }}
                onKeyDown={(e) => {
                  // Escrever o nome e carregar em Enter é o gesto de quem tem
                  // teclado; sem isto obrigava-se a ir com o rato ao botão.
                  if (e.key === 'Enter') { e.preventDefault(); seguinte(); }
                }}
                maxLength={MAX_TEXTO}
                disabled={aGravar}
                placeholder="Escreva aqui"
                className="h-16 text-2xl md:text-2xl"
              />
              <p className="text-xs text-muted-foreground">
                Fica na conta e sai no talão da cozinha.
              </p>
            </div>
          ) : (
            <>
              {opcoesVisiveis.length > 0 ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                  {opcoesVisiveis.map((opcao) => {
                    const doses = dosesDe(opcoes, grupo.id, opcao.id);
                    return (
                      <BotaoOpcao
                        key={opcao.id}
                        opcao={opcao}
                        doses={doses}
                        alternativa={max === 1}
                        // Num grupo de alternativas nunca se desliga nada:
                        // tocar noutra troca, e é assim que se corrige um
                        // engano. Só um máximo de 2 ou mais fecha a porta —
                        // e diz logo por baixo como se abre.
                        desligado={aGravar || (noMaximo && doses === 0)}
                        onDose={() => juntarDose(opcao)}
                        onApagar={() => apagarOpcao(opcao)}
                      />
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  Este passo não tem opções disponíveis.
                </p>
              )}

              {opcoesVisiveis.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {max === 1
                    ? 'Toque para escolher — tocar noutra troca.'
                    : 'Toque para juntar outra dose · carregue 2 segundos para apagar.'}
                </p>
              )}

              {noMaximo && (
                <p className="text-xs text-muted-foreground">
                  Máximo atingido — apague uma para trocar.
                </p>
              )}
            </>
          )}

          <BlocoErros erros={avisar ? errosDoPasso : []} />
        </div>

        <div className="border-t p-4 flex items-center gap-3 shrink-0">
          <Button
            variant="outline"
            className="h-14 px-6 text-base"
            onClick={() => setPasso(Math.max(indice - 1, 0))}
            disabled={indice === 0 || aGravar}
          >
            <ChevronLeft className="h-5 w-5 mr-1" />
            Anterior
          </Button>
          <Button
            className="h-14 flex-1 text-base"
            onClick={seguinte}
            disabled={aGravar}
          >
            {aGravar ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : ultimo ? (
              'Gravar'
            ) : (
              <>
                Seguinte
                <ChevronRight className="h-5 w-5 ml-1" />
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
