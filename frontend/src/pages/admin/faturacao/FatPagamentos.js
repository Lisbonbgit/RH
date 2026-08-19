import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getTiposPagamento, getCodigosFiscais, getMetodosVendus,
  criarTipoPagamento, editarTipoPagamento, apagarTipoPagamento,
  detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Switch } from '../../../components/ui/switch';
import { RadioGroup, RadioGroupItem } from '../../../components/ui/radio-group';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import {
  CreditCard, Plus, Pencil, Trash2, Lock, Banknote, Ban, AlertTriangle, RefreshCw, HelpCircle,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const emptyForm = { nome: '', tipo_fiscal: '', da_troco: null, ordem: '0', ativo: true, vendus_payment_method_id: null };

const AVISO_PROTEGIDO = "Este tipo de pagamento é usado pela app L'Açaí e não pode ser alterado nem apagado aqui.";

// O <Select> do Radix não aceita um item de valor vazio, e "sem método do
// Vendus" é uma escolha legítima (um tipo pode existir por ligar). Daí um
// valor-sentinela, traduzido de e para `null` nas duas fronteiras do
// formulário — nunca sai daqui para o servidor.
const SEM_METODO = '__sem_metodo__';

// A frase exacta com que fiscal.py::finalizar recusa a emissão. Está aqui
// escrita à letra de propósito: é o que a operadora vai ver no balcão, e quem
// estiver a mapear tem de reconhecer as duas pontas como a mesma coisa.
const RECUSA_DO_SERVIDOR = 'Este tipo de pagamento não tem um método do Vendus associado — não pode ser usado para emitir uma fatura real.';

// A metade do trabalho que NÃO se faz neste ecrã, escrita uma vez e mostrada
// onde a pergunta nasce.
//
// O ecrã explicava muito bem a CONSEQUÊNCIA de um tipo ficar por ligar ("no POS
// o botão aparece morto") e em lado nenhum o PASSO SEGUINTE: um método de
// pagamento não se cria aqui, cria-se do lado do Vendus. Quem procurasse "MB
// Way" na lista e não o encontrasse gravava o tipo à mesma, ficava com o selo
// vermelho "Não emite faturas", e não tinha como adivinhar que a peça que
// faltava estava do outro lado — que é exactamente o oposto do que este ecrã
// existe para fazer: o dono chegar ao fim sozinho, sem chamar um programador.
//
// NÃO se nomeia o caminho exacto dentro do backoffice do Vendus de propósito.
// Um menu que não exista na versão da conta dele manda-o procurar onde não está
// e leva atrás a confiança na frase toda; "nos métodos de pagamento" é como a
// coisa se chama dos dois lados, e chega para a encontrar.
const ONDE_CRIAR_O_METODO = 'Os métodos de pagamento criam-se no backoffice do Vendus, nos métodos de pagamento — aqui só se escolhe entre os que já lá existem.';

// O passo seguinte, e é ESTA frase que muda o desenho todo do campo.
//
// Ela dizia "carregue em «Atualizar lista»" — e mandava fazer uma coisa que
// não funcionava. Enquanto o <Select> do Radix está aberto, o DismissableLayer
// põe `pointer-events: none` em tudo o que está por baixo dele, botão
// incluído: o clique de quem lê a frase com a lista aberta (que é quando ela
// se lê) só fechava a lista. Sem roda a girar, sem pedido nenhum ao servidor,
// sem mensagem — e a lista reabria com a mesma frase a mandá-lo carregar no
// botão em que acabou de carregar. Uma armadilha perfeita, e nenhum sinal.
//
// A lista passou a reler-se sozinha SEMPRE QUE É ABERTA, que é o gesto natural
// de quem volta do backoffice do Vendus à procura do método que lá criou. Não
// há botão para acertar, não há camada a comer o clique, e a frase deixou de
// pedir um gesto que falha: pede o gesto que a pessoa ia fazer de qualquer
// maneira.
const DEPOIS_DE_CRIAR = 'Crie-o lá, volte aqui e abra outra vez esta lista: ela é lida do Vendus de cada vez que a abre.';

// A pausa mínima entre duas leituras automáticas da lista. Ver `carregarMetodos`.
const PAUSA_ENTRE_LEITURAS_MS = 5000;

// Sem lista de métodos há três estados possíveis, e o próximo passo do dono é
// DIFERENTE em cada um. Tratá-los como um só ("não foi possível obter a lista")
// era mandá-lo bater à porta errada:
//
//   400 — a ligação à conta Vendus não está feita NESTE servidor. Não há nada
//         que ele possa fazer, nem no Vendus nem aqui. A mensagem do servidor
//         fala de VENDUS_ACCOUNTS e de ficheiros .env: continua a aparecer,
//         para quem a saiba ler, mas em último lugar e nunca sozinha — a
//         primeira coisa tem de ser a única frase accionável, que é falar com
//         quem instalou o sistema. E o botão de tentar de novo desaparece:
//         insistir nele nunca vai dar resultado nenhum, e um botão que não
//         pode funcionar é pior do que botão nenhum.
//   502 — o Vendus está em baixo. Passa; tentar outra vez daqui a um minuto é
//         mesmo a coisa certa a fazer, e o botão fica.
//   lista vazia — a conta respondeu e não tem métodos criados. A resposta é a
//         mesma do ONDE_CRIAR_O_METODO: o trabalho é do lado de lá.
//
// É AQUI que o botão de reler a lista continua a fazer falta, e só aqui: nestes
// três estados não há <Select> nenhum montado — não há lista para abrir, e sem
// botão não havia gesto nenhum que trouxesse a lista sem recarregar a página.
// É também o único sítio onde o botão pode mesmo ser carregado: sem popper
// aberto por cima, não há camada a comer o clique (ver o DEPOIS_DE_CRIAR).
// No caminho bom o botão desapareceu — quem abre a lista já a está a reler.
//
// `rotuloTentar` muda com a causa porque o gesto não é o mesmo: com o Vendus em
// baixo insiste-se no mesmo pedido, com a conta vazia vem-se buscar um método
// que entretanto se criou lá.
const explicarSemLista = (erro) => {
  if (erro && erro.estado === 400) {
    return {
      tom: 'perigo',
      titulo: 'A ligação à conta Vendus ainda não está feita neste servidor',
      corpo: 'Enquanto isto não estiver feito, nenhum tipo de pagamento consegue emitir faturas — e não é '
        + 'coisa que se resolva a partir deste ecrã. Fale com quem lhe instalou o sistema e peça para ligar a '
        + 'conta Vendus a este portal.',
      tecnico: erro.mensagem,
      podeTentarDeNovo: false,
      rotuloTentar: null,
    };
  }
  if (erro) {
    return {
      tom: 'aviso',
      titulo: 'Não foi possível falar com o Vendus',
      corpo: 'A lista de métodos não chegou, por isso não dá para escolher nem confirmar nenhum. As ligações '
        + 'que já estão gravadas continuam de pé — o que não dá, para já, é mexer nelas. Tente outra vez daqui '
        + 'a um minuto; se continuar assim, fale com quem lhe instalou o sistema.',
      tecnico: erro.mensagem,
      podeTentarDeNovo: true,
      rotuloTentar: 'Tentar outra vez',
    };
  }
  return {
    tom: 'aviso',
    titulo: 'A conta Vendus não tem nenhum método de pagamento',
    // Aqui a frase manda mesmo carregar no botão — e pode: sem métodos não há
    // lista para abrir, o botão está sozinho no ecrã e o clique chega-lhe.
    corpo: 'A conta respondeu, mas está sem métodos criados. ' + ONDE_CRIAR_O_METODO
      + ' Depois de criar o primeiro, carregue em "Atualizar lista" aqui em baixo.',
    tecnico: null,
    podeTentarDeNovo: true,
    rotuloTentar: 'Atualizar lista',
  };
};

const estadoBadge = (ativo) => (
  ativo !== false
    ? <Badge variant="outline" className="bg-teal-50 text-teal-700 border-teal-200">Ativo</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Inativo</Badge>
);

const trocoBadge = (daTroco) => (
  daTroco
    ? <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 gap-1"><Banknote className="h-3 w-3" />Dá troco</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Não dá troco</Badge>
);

// O id vem da lista do Vendus como número e do nosso registo como texto (as
// quatro ligações que existem hoje foram postas à mão na base de dados de
// produção). Comparar e guardar sempre a forma-texto evita as duas versões do
// mesmo defeito: um `145234375 !== '145234375'` que mostrava "já não consta na
// conta Vendus" a um mapeamento perfeitamente válido, e um número enviado a um
// campo que o servidor declara `Optional[str]`, que voltaria em 422.
const comoTexto = (valor) => (valor === null || valor === undefined || valor === '' ? null : String(valor));

// Um bloco de aviso dentro do formulário — mesmo desenho do FatReservasPresas,
// mas com os tokens `warning`/`destructive` do tema (index.css define-os para
// claro E escuro) em vez de cores fixas.
function Bloco({ tom = 'neutro', icone: Icone, titulo, children, testid }) {
  const tons = {
    neutro: 'border-border bg-muted/40',
    aviso: 'border-warning/40 bg-warning/10',
    perigo: 'border-destructive/40 bg-destructive/10',
  };
  const tonsIcone = {
    neutro: 'text-muted-foreground',
    aviso: 'text-warning',
    perigo: 'text-destructive',
  };
  return (
    <div className={`rounded-lg border p-3 text-sm space-y-1.5 ${tons[tom] || tons.neutro}`} data-testid={testid}>
      {titulo && (
        <p className="font-semibold flex items-start gap-1.5">
          {Icone && <Icone className={`h-4 w-4 shrink-0 mt-0.5 ${tonsIcone[tom] || tonsIcone.neutro}`} />}
          <span>{titulo}</span>
        </p>
      )}
      {children}
    </div>
  );
}

// O servidor deixa `titulo` sair vazio de propósito (um método sem título na
// conta Vendus é para mostrar, não para esconder) — mas uma linha em branco
// numa lista de escolha não se pode escolher com confiança. Cai-se então para
// o id, que é o que identifica mesmo o método.
const tituloMetodo = (metodo) => (metodo.titulo || '').trim() || `#${comoTexto(metodo.id)}`;

// "Dinheiro · NU" — o título que o dono reconhece e o código fiscal que o
// Vendus vai pôr na fatura, lado a lado. O código não é decorativo: é ele que
// permite reparar que o "Uber" está OU do nosso lado e TB do lado de lá.
const rotuloMetodo = (metodo) => (
  metodo.tipo_fiscal ? `${tituloMetodo(metodo)} · ${metodo.tipo_fiscal}` : tituloMetodo(metodo)
);

// Com SEGUNDOS de propósito: sem eles, uma releitura bem-sucedida dentro do
// mesmo minuto deixava o cabeçalho letra por letra igual — e "não aconteceu
// nada" ficava indistinguível de "li e não havia nada de novo".
const horaCurta = (data) =>
  data.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

// O estado da leitura da lista, em texto.
//
// Uma leitura que corria BEM não dizia absolutamente nada: o único sinal era
// uma roda a girar num botão, e quando ela parava o ecrã ficava exactamente
// como estava. Ou seja, um clique perdido e uma leitura bem-sucedida produziam
// a mesma imagem — que é como quem tinha acabado de criar o método no Vendus
// não conseguia saber se o ecrã já tinha ido buscar a lista nova ou não.
//
// A hora resolve isso sem inventar entusiasmo nenhum: "lida às 14:32" muda
// para "14:33" à frente dos olhos, e é verdade mesmo quando não veio nada de
// novo. Um toast anuncia o resto (ver `anunciarLeitura`).
function EstadoDaLeitura({ carregando, lidaEm, testid }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" data-testid={testid}>
      <RefreshCw className={`h-3 w-3 shrink-0 ${carregando ? 'animate-spin' : ''}`} />
      {carregando
        ? 'A ler a lista do Vendus…'
        : (lidaEm ? `Lista lida às ${horaCurta(lidaEm)}` : 'Lista por ler')}
    </span>
  );
}

// O anúncio de uma leitura que correu bem.
//
// O caso que interessa é um só: o método que ele foi criar ao Vendus APARECEU.
// Dizê-lo pelo nome é o fim da viagem — a confirmação de que as duas metades
// do trabalho (a de lá e a de cá) se encontraram. Sem novidade nenhuma
// cala-se, senão abrir a lista três vezes seguidas enchia o canto do ecrã de
// avisos iguais a dizer que nada mudou; nesse caso é a hora do
// `EstadoDaLeitura` que responde.
//
// A excepção é o botão: um botão que se carrega tem de responder SEMPRE, mesmo
// que a resposta seja "está tudo na mesma" — é o que distingue um clique
// atendido de um clique que se perdeu.
const anunciarLeitura = (motivo, lista, novos) => {
  if (novos && novos.length === 1) {
    toast.success(`"${tituloMetodo(novos[0])}" apareceu na lista de métodos do Vendus`);
    return;
  }
  if (novos && novos.length > 1) {
    toast.success(`${novos.length} métodos novos apareceram na lista do Vendus`);
    return;
  }
  if (motivo !== 'pedido') return;
  if (lista.length === 0) {
    toast.info('A conta Vendus continua sem métodos de pagamento');
    return;
  }
  const quantos = `${lista.length} ${lista.length === 1 ? 'método' : 'métodos'}`;
  // `novos` a null quer dizer que não havia lista anterior com que comparar
  // (a primeira leitura, ou a primeira depois de uma que falhou). Dizer
  // "nenhum novo" aí seria afirmar uma coisa que não se sabe.
  toast.success(novos ? `Lista atualizada — ${quantos}, nenhum novo` : `Lista atualizada — ${quantos}`);
};

export default function FatPagamentos() {
  const [tipos, setTipos] = useState([]);
  const [codigosFiscais, setCodigosFiscais] = useState({});
  const [loading, setLoading] = useState(true);

  // Os métodos do Vendus vivem em estado próprio, com o seu próprio erro: a
  // lista vem da rede, de uma conta que pode nem estar configurada, e este
  // ecrã tem de continuar a servir para tudo o resto sem ela.
  const [metodos, setMetodos] = useState([]);
  const [erroMetodos, setErroMetodos] = useState(null);
  const [carregandoMetodos, setCarregandoMetodos] = useState(true);
  // A hora da última leitura BEM-SUCEDIDA, para o `EstadoDaLeitura`.
  const [lidaEm, setLidaEm] = useState(null);
  // "Já houve pelo menos uma tentativa", que não é o mesmo que "está a
  // carregar": é isto que permite ao cartão de falha ficar de pé enquanto se
  // tenta outra vez sem aparecer, vermelho, no arranque de toda a gente.
  const [jaLeuMetodos, setJaLeuMetodos] = useState(false);

  // Refs e não estado: são lidos DENTRO do `carregarMetodos`, que é um
  // useCallback sem dependências (para não reconstruir o `fetchAll` e o efeito
  // que dele depende a cada leitura). Estado ali dentro vinha sempre com o
  // valor do primeiro render.
  const leituraEmVooRef = useRef(false);
  const ultimaLeituraRef = useRef(0);
  const metodosRef = useRef([]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  // `useCallback` nas duas, e as duas antes do efeito, como no
  // FatReservasPresas: assim que o `fetchAll` passou a chamar outra função do
  // componente deixou de ser estável aos olhos do react-hooks/exhaustive-deps,
  // e a lista de dependências vazia que o ecrã tinha passou a dar aviso no
  // build. Declarar a intenção (deps explícitas) é preferível a calar o aviso.
  //
  // A lista relê-se por quatro motivos, e nem todos merecem a mesma coisa:
  //
  //   'arranque'  — a página montou.
  //   'dialogo'   — o formulário abriu.
  //   'abertura'  — a LISTA de métodos foi aberta. É o gesto de quem volta do
  //                 backoffice do Vendus à procura do método que lá criou, e é
  //                 por causa dele que este ecrã deixou de precisar do botão
  //                 (ver o DEPOIS_DE_CRIAR).
  //   'pedido'    — alguém carregou no botão, que só existe onde não há lista.
  const carregarMetodos = useCallback(async ({ motivo = 'arranque' } = {}) => {
    // Dois travões, e nenhum se aplica ao botão:
    //
    //   1. uma leitura de cada vez. Abrir e fechar a lista depressa não põe
    //      duas a correr contra a mesma conta, nem deixa a resposta de trás
    //      chegar depois da da frente e mandar no ecrã.
    //   2. uma pausa mínima entre leituras automáticas. Sem ela, abrir a lista
    //      cinco vezes a confirmar uma escolha eram cinco chamadas ao Vendus
    //      em poucos segundos, todas com a mesma resposta. Cinco segundos não
    //      atrapalham o caso que interessa — ir ao Vendus, criar lá o método e
    //      voltar demora sempre muito mais — e a leitura saltada não engana
    //      ninguém: a lista mostra a hora a que foi lida, e ela é de há
    //      segundos.
    //
    // NÃO há releitura periódica. Isto é um ecrã de configuração que se abre
    // quando entra um método novo; um pedido a repetir-se sozinho contra uma
    // conta externa não se justifica.
    // Uma leitura de cada vez, sempre: duas em voo davam respostas a chegar
    // fora de ordem, e a lista podia acabar na versão mais VELHA das duas.
    if (leituraEmVooRef.current) return;
    // A pausa trava só o que acontece SEM ninguém pedir (o arranque da página,
    // a abertura do diálogo). Abrir a lista é um gesto da pessoa, tal como
    // carregar no botão — e é precisamente o gesto de quem acabou de criar o
    // método no Vendus e voltou aqui. Travá-lo desmentia a frase que este
    // ecrã lhe dá ("é lida do Vendus de cada vez que a abre"): quem criasse o
    // método noutro separador e voltasse em menos de cinco segundos não via
    // pedido nenhum, e a hora ao minuto não deixava perceber que a leitura
    // tinha sido saltada. Uma frase falsa num ecrã é pior do que a leitura a
    // mais que ela custa.
    if (motivo === 'arranque' || motivo === 'dialogo') {
      if (Date.now() - ultimaLeituraRef.current < PAUSA_ENTRE_LEITURAS_MS) return;
    }
    leituraEmVooRef.current = true;
    setCarregandoMetodos(true);
    try {
      const { data } = await getMetodosVendus();
      const lista = Array.isArray(data) ? data : [];
      // O que é "novo" só se pode dizer contra uma lista que já existia: da
      // primeira vez que ela chega são todos novos, e anunciar "6 métodos
      // novos" a quem abriu o ecrã agora seria uma mentira. Sem lista anterior
      // vai `null` — "não há com que comparar" — e não uma lista vazia, que se
      // leria como "comparei e não havia nada de novo".
      const antes = new Set(metodosRef.current.map((m) => comoTexto(m.id)));
      const novos = antes.size > 0 ? lista.filter((m) => !antes.has(comoTexto(m.id))) : null;
      metodosRef.current = lista;
      setMetodos(lista);
      setErroMetodos(null);
      setLidaEm(new Date());
      anunciarLeitura(motivo, lista, novos);
    } catch (error) {
      // A mensagem do servidor já vem escrita em português e a dizer o que
      // falta (conta por configurar, Vendus em baixo) — não se resume nem se
      // troca por um "ocorreu um erro".
      const { mensagem } = detalhesErro(error, 'Não foi possível obter a lista de métodos de pagamento do Vendus.');
      metodosRef.current = [];
      setMetodos([]);
      // O ESTADO viaja com a mensagem porque as duas falhas pedem coisas
      // diferentes ao dono: um 400 é configuração NOSSA por fazer (só se
      // resolve com quem instalou o sistema — ver `explicarSemLista`), um 502
      // é o Vendus em baixo (tentar outra vez daqui a bocado resolve). Guardar
      // só a frase deixava o ecrã sem forma de os distinguir.
      setErroMetodos({ estado: error.response?.status || null, mensagem });
      // Falhar com a lista ABERTA fá-la desaparecer debaixo dos olhos (fica o
      // bloco a explicar porquê) — e uma coisa que se desfaz sozinha tem de
      // ser dita. No arranque e na abertura do formulário a explicação já está
      // no cartão e no bloco, e o toast só repetia.
      if (motivo === 'pedido' || motivo === 'abertura') {
        toast.error('Não foi possível ler a lista de métodos do Vendus');
      }
    } finally {
      leituraEmVooRef.current = false;
      ultimaLeituraRef.current = Date.now();
      setCarregandoMetodos(false);
      setJaLeuMetodos(true);
    }
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [t, c] = await Promise.all([getTiposPagamento(), getCodigosFiscais()]);
      setTipos(t.data || []);
      setCodigosFiscais(c.data || {});
    } catch (error) {
      toast.error('Erro ao carregar tipos de pagamento');
    } finally {
      setLoading(false);
    }
    // Fora do Promise.all acima de propósito: uma rejeição ali levava consigo
    // as duas chamadas que já tinham respondido e deixava a página vazia por
    // causa de uma lista que é acessória à maior parte do trabalho aqui.
    carregarMetodos();
  }, [carregarMetodos]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const metodosPorId = useMemo(
    () => new Map(metodos.map((m) => [comoTexto(m.id), m])),
    [metodos],
  );

  const listaDisponivel = metodos.length > 0;
  // Com a conta por configurar não há nada para actualizar, e por isso o
  // `podeTentarDeNovo` desliga os dois botões de reler a lista em vez de os
  // deixar a prometer o que nunca vão cumprir. Ver o 400 em `explicarSemLista`.
  const explicacaoSemLista = explicarSemLista(erroMetodos);

  // Um id gravado que a lista do Vendus não reconhece: o método foi apagado ou
  // renomeado do lado de lá, e a emissão vai bater na parede. Só se pode
  // AFIRMAR com a lista à frente — sem ela não se sabe se o método ainda lá
  // está, e acusar por adivinhação era pior do que calar.
  const metodoApagadoNoVendus = (tipo) => {
    const id = comoTexto(tipo.vendus_payment_method_id);
    return listaDisponivel && !!id && !metodosPorId.has(id);
  };

  // Activo e sem emitir é o caso perigoso: no POS o botão aparece (morto, mas
  // aparece) e tudo o resto neste ecrã diz "Ativo". Um tipo inativo por ligar
  // não emite nada porque não é usado — é arrumação, não uma avaria.
  //
  // São DUAS as maneiras de não emitir, e o cartão do topo contava só uma. Com
  // o Glovo por ligar e o "Bolt" apontado a um id que já não existe no Vendus,
  // dizia "1 tipo de pagamento ativo não emite faturas" — e eram dois. Quem
  // confiasse no número corrigia o Glovo, via o aviso desaparecer, e ficava
  // convencido de que estava tudo bem enquanto o Bolt continuava a recusar
  // faturas ao balcão.
  const naoEmite = (tipo) => (
    tipo.ativo !== false && (!tipo.vendus_payment_method_id || metodoApagadoNoVendus(tipo))
  );

  const activosQueNaoEmitem = tipos.filter(naoEmite);

  // A lista do Vendus é relida sempre que o diálogo abre, e não só ao montar a
  // página. É o passo seguinte ao conselho do ONDE_CRIAR_O_METODO, e sem ele o
  // conselho não servia de nada: o dono ia ao Vendus, criava lá o método, e o
  // ecrã continuava a mostrar a lista velha — fechar em "Cancelar" e reabrir
  // não trazia nada, só o F5 trazia, e ninguém lhe disse isso.
  //
  // A outra releitura, a que fecha mesmo o percurso, está no <Select>: abrir a
  // lista lê-a. Quem volta do Vendus não fecha e reabre o formulário — abre a
  // lista à procura do método que criou.
  const openNew = () => {
    setEditing(null);
    setForm(emptyForm);
    setFieldErrors({});
    carregarMetodos({ motivo: 'dialogo' });
    setDialogOpen(true);
  };

  // O ecrã não deixa sequer tentar editar um tipo protegido (o servidor
  // devolve 409, mas o botão de editar nem chega a abrir o formulário).
  const openEdit = (tipo) => {
    if (tipo.protegido) {
      toast.info(AVISO_PROTEGIDO);
      return;
    }
    setEditing(tipo);
    setForm({
      nome: tipo.nome || '',
      tipo_fiscal: tipo.tipo_fiscal || '',
      da_troco: tipo.da_troco === true,
      ordem: String(tipo.ordem ?? 0),
      ativo: tipo.ativo !== false,
      // O mapeamento entra no formulário TAL COMO ESTÁ no registo, mesmo que
      // a lista do Vendus não tenha vindo e mesmo que aponte para um método
      // que já lá não exista. É esta linha (com a do payload, mais abaixo)
      // que impede o defeito antigo: o PUT substitui o registo inteiro, e um
      // campo que não volte no pedido fica a null — gravar o nome de um tipo
      // que estava a emitir desligava-o em silêncio.
      vendus_payment_method_id: comoTexto(tipo.vendus_payment_method_id),
    });
    setFieldErrors({});
    carregarMetodos({ motivo: 'dialogo' });  // ver o comentário do openNew
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.nome.trim()) { toast.error('Indique o nome do tipo de pagamento'); return; }
    if (!form.tipo_fiscal) { toast.error('Escolha o código fiscal'); return; }
    if (form.da_troco === null) { toast.error("Escolha se este tipo de pagamento dá troco"); return; }
    const payload = {
      nome: form.nome.trim(),
      tipo_fiscal: form.tipo_fiscal,
      da_troco: form.da_troco,
      ordem: parseInt(form.ordem, 10) || 0,
      ativo: form.ativo,
      // Vai sempre, na criação e na edição — ver o comentário do openEdit.
      // Deixar de o enviar quando a lista do Vendus falhou seria repor
      // exactamente o defeito que este campo veio fechar.
      vendus_payment_method_id: form.vendus_payment_method_id || null,
    };
    setSaving(true);
    setFieldErrors({});
    try {
      if (editing) { await editarTipoPagamento(editing.id, payload); toast.success('Tipo de pagamento atualizado'); }
      else { await criarTipoPagamento(payload); toast.success('Tipo de pagamento criado'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || AVISO_PROTEGIDO);
        setDialogOpen(false);
        fetchAll();
        return;
      }
      if (status === 404) {
        toast.error('Este tipo de pagamento já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { campo, mensagem } = detalhesErro(error, 'Erro ao guardar o tipo de pagamento');
      if (campo) setFieldErrors({ [campo]: mensagem });
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const askDelete = (tipo) => {
    if (tipo.protegido) {
      toast.info(AVISO_PROTEGIDO);
      return;
    }
    setDeleteTarget(tipo);
  };

  const handleDelete = async () => {
    const alvo = deleteTarget;
    setDeleteTarget(null);
    try {
      await apagarTipoPagamento(alvo.id);
      toast.success('Tipo de pagamento eliminado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || AVISO_PROTEGIDO);
        fetchAll();
      } else if (status === 404) {
        toast.error('Este tipo de pagamento já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar o tipo de pagamento');
      }
    }
  };

  // --- A célula do mapeamento, na tabela -------------------------------------
  // Sem isto não havia forma nenhuma de ver quais os tipos por ligar sem os
  // abrir um a um — e um tipo por ligar parece pronto em todas as outras
  // colunas.
  const celulaVendus = (tipo) => {
    const id = comoTexto(tipo.vendus_payment_method_id);
    const activo = tipo.ativo !== false;

    if (!id) {
      return activo ? (
        <Badge variant="destructive" className="gap-1" data-testid={`pagamento-sem-vendus-${tipo.id}`}>
          <Ban className="h-3 w-3" />Não emite faturas
        </Badge>
      ) : (
        <Badge variant="outline" className="text-muted-foreground gap-1" data-testid={`pagamento-sem-vendus-${tipo.id}`}>
          <Ban className="h-3 w-3" />Por ligar
        </Badge>
      );
    }

    if (!listaDisponivel) {
      // A lista não veio: sabe-se que ESTÁ ligado, não a quê. Dizer "método
      // desconhecido" aqui era acusar de avaria um mapeamento que está bom.
      //
      // Mas o número sozinho e a cinzento LIA-SE COMO SE ESTIVESSE BEM, e era
      // aí que estava o defeito: com a lista fora do ar, a linha de um tipo
      // apontado a um método que já não consta no Vendus (a âmbar, com "já não
      // consta no Vendus", quando há lista) ficava igualzinha à de um tipo bem
      // ligado. Um problema real desaparecia do ecrã porque outro tinha
      // aparecido. "Por confirmar" diz o que se sabe mesmo — que está ligado e
      // que ninguém verificou a quê — e o cartão no topo da página diz porquê.
      return (
        <span
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"
          title="A lista de métodos do Vendus não veio, por isso não foi possível confirmar esta ligação."
          data-testid={`pagamento-vendus-por-confirmar-${tipo.id}`}
        >
          <HelpCircle className="h-3.5 w-3.5 shrink-0" />
          <span className="font-mono">#{id}</span>
          <span className="text-xs">por confirmar</span>
        </span>
      );
    }

    const metodo = metodosPorId.get(id);
    if (!metodo) {
      // A lista veio e este id não está lá: o método foi apagado ou renomeado
      // na conta Vendus. A emissão vai bater na parede do lado de lá.
      return (
        <span className="inline-flex items-center gap-1.5 text-sm text-warning" data-testid={`pagamento-vendus-orfao-${tipo.id}`}>
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span className="font-mono">#{id}</span>
          <span className="text-xs">já não consta no Vendus</span>
        </span>
      );
    }

    const divergente = metodo.tipo_fiscal && tipo.tipo_fiscal && metodo.tipo_fiscal !== tipo.tipo_fiscal;
    return (
      <span className="text-sm" data-testid={`pagamento-vendus-${tipo.id}`}>
        {tituloMetodo(metodo)}
        {metodo.tipo_fiscal && <span className="text-muted-foreground"> · {metodo.tipo_fiscal}</span>}
        {divergente && (
          <span
            className="ml-1.5 text-xs text-warning"
            title={`Código fiscal diferente do daqui (${tipo.tipo_fiscal}). O que sai na fatura é o do Vendus.`}
          >
            (difere)
          </span>
        )}
      </span>
    );
  };

  // --- O campo, no diálogo ---------------------------------------------------
  const metodoEscolhido = form.vendus_payment_method_id ? metodosPorId.get(form.vendus_payment_method_id) : null;
  // Um mapeamento que a lista não reconhece precisa de item próprio: sem ele o
  // <Select> mostrava o gatilho VAZIO — indistinguível de "sem método" — com o
  // valor ainda guardado por baixo.
  const idOrfao = (listaDisponivel && form.vendus_payment_method_id && !metodoEscolhido)
    ? form.vendus_payment_method_id
    : null;
  const fiscalDivergente = metodoEscolhido && metodoEscolhido.tipo_fiscal && form.tipo_fiscal
    && metodoEscolhido.tipo_fiscal !== form.tipo_fiscal;

  // Só entra no formulário o que este campo REALMENTE oferece: o sentinela, um
  // método da lista, ou o id órfão que o próprio campo acrescentou.
  //
  // O defeito que isto fecha foi apanhado a correr o ecrã, não a lê-lo: o
  // <Select> do Radix dispara `onValueChange('')` sozinho quando o valor
  // controlado não casa com nenhum item montado — que é exactamente o caso de
  // um tipo apontado a um método entretanto apagado no Vendus. Sem este
  // crivo, esse '' era escrito no formulário como se fosse uma escolha da
  // pessoa: o diálogo passava a dizer "Sem método — este tipo não emite
  // faturas" enquanto a tabela, ao lado, continuava a mostrar o id gravado, e
  // um Guardar sem tocar em nada enviava `null` para um campo em que ninguém
  // mexeu. A regra é a mesma do resto do ecrã: o mapeamento só muda quando
  // alguém o muda.
  const escolherMetodo = (valor) => {
    if (valor !== SEM_METODO && valor !== idOrfao && !metodosPorId.has(valor)) return;
    setForm((anterior) => ({
      ...anterior,
      vendus_payment_method_id: valor === SEM_METODO ? null : valor,
    }));
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-pagamentos-page">
      <PageHeader icon={CreditCard} title="Tipos de Pagamento" subtitle="Meios de pagamento aceites, os seus códigos fiscais e o método a que correspondem no Vendus">
        <Button onClick={openNew} data-testid="add-pagamento-btn"><Plus className="h-4 w-4 mr-2" />Novo tipo</Button>
      </PageHeader>

      {!loading && activosQueNaoEmitem.length > 0 && (
        <Card className="border-destructive/50 bg-destructive/10" data-testid="pagamentos-por-ligar-aviso">
          <CardContent className="p-4 flex items-start gap-3">
            <div className="h-9 w-9 rounded-full bg-destructive/15 flex items-center justify-center shrink-0">
              <Ban className="h-4 w-4 text-destructive" />
            </div>
            <div className="space-y-2">
              <p className="text-sm font-semibold">
                {activosQueNaoEmitem.length === 1
                  ? '1 tipo de pagamento ativo não emite faturas'
                  : `${activosQueNaoEmitem.length} tipos de pagamento ativos não emitem faturas`}
              </p>
              <p className="text-sm text-muted-foreground">
                Ou não têm método do Vendus escolhido, ou apontam para um método que já não existe na
                conta Vendus. No balcão o botão aparece morto e, se a emissão chegar a ser tentada, o
                servidor recusa-a — a venda fica por fechar com o cliente à frente. Abra cada um e
                trate do "Método no Vendus".
              </p>
              <div className="flex flex-wrap gap-1.5">
                {activosQueNaoEmitem.map((t) => (
                  <Badge key={t.id} variant="outline" className="gap-1" data-testid={`por-ligar-${t.id}`}>
                    {t.protegido && <Lock className="h-3 w-3" />}
                    {t.nome}
                    {/* Os dois motivos não se corrigem da mesma maneira: um
                        pede escolher um método, o outro pede perceber o que
                        aconteceu ao método do lado do Vendus. Um número certo
                        com todos os nomes iguais mandava-o abrir cada um para
                        descobrir qual era qual. */}
                    {metodoApagadoNoVendus(t) && (
                      <span className="text-muted-foreground">· método apagado no Vendus</span>
                    )}
                  </Badge>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* A lista do Vendus não veio — e a página tem de o dizer.

          Sem este cartão a tabela passava a mostrar ids crus e mais nada: sem
          aviso, sem toast e sem botão. O erro estava guardado, mas só o
          diálogo o lia — ou seja, só quem já tivesse aberto um tipo para
          editar. Quem só olhasse para a tabela via uma página normal.

          A condição é `jaLeuMetodos` e NÃO `!carregandoMetodos`, que é uma
          diferença de uma palavra e de todo o comportamento: preso ao
          "carregando", o cartão inteiro — com o botão lá dentro — desaparecia
          enquanto se tentava outra vez. Carregar em "Tentar outra vez" apagava
          a explicação da falha e deixava no ecrã uma tabela de aspecto
          saudável durante os até 20 s que o Vendus leva a responder mal; ou se
          concluía que estava resolvido, ou se ficava sem saber — e depois o
          cartão ressurgia sem explicação nenhuma. Agora fica de pé, com o
          estado da tentativa no botão. `jaLeuMetodos` é o que impede o outro
          extremo: aparecer, vermelho, no arranque de toda a gente, antes
          sequer de a primeira resposta chegar. */}
      {!loading && jaLeuMetodos && !listaDisponivel && (
        <Card
          className={explicacaoSemLista.tom === 'perigo'
            ? 'border-destructive/50 bg-destructive/10'
            : 'border-warning/50 bg-warning/10'}
          data-testid="pagamentos-sem-lista-vendus-aviso"
        >
          <CardContent className="p-4 flex items-start gap-3">
            <div className={`h-9 w-9 rounded-full flex items-center justify-center shrink-0 ${
              explicacaoSemLista.tom === 'perigo' ? 'bg-destructive/15' : 'bg-warning/15'}`}
            >
              <AlertTriangle className={`h-4 w-4 ${
                explicacaoSemLista.tom === 'perigo' ? 'text-destructive' : 'text-warning'}`}
              />
            </div>
            <div className="space-y-2">
              <p className="text-sm font-semibold">{explicacaoSemLista.titulo}</p>
              <p className="text-sm text-muted-foreground">{explicacaoSemLista.corpo}</p>
              {tipos.some((t) => t.vendus_payment_method_id) && (
                <p className="text-sm text-muted-foreground">
                  Na tabela, os tipos já ligados aparecem com o número do método e a nota
                  {' '}<strong>"por confirmar"</strong>: sabe-se que estão ligados, não a quê — nem se
                  o método ainda existe do lado do Vendus.
                </p>
              )}
              {explicacaoSemLista.podeTentarDeNovo && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => carregarMetodos({ motivo: 'pedido' })}
                  disabled={carregandoMetodos}
                  data-testid="recarregar-metodos-vendus-pagina-btn"
                >
                  <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${carregandoMetodos ? 'animate-spin' : ''}`} />
                  {carregandoMetodos ? 'A ler a lista do Vendus…' : explicacaoSemLista.rotuloTentar}
                </Button>
              )}
              {/* Em último lugar e nunca sozinha: a mensagem do servidor fala
                  de VENDUS_ACCOUNTS e de ficheiros .env, que não é nada que
                  esteja ao alcance de quem gere as lojas. Continua cá para
                  quem a saiba ler — a seguir à frase que ele pode mesmo
                  usar. */}
              {explicacaoSemLista.tecnico && (
                <p className="text-xs text-muted-foreground pt-1">
                  <span className="font-medium">Para quem for tratar disto:</span>{' '}
                  {explicacaoSemLista.tecnico}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : tipos.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CreditCard className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem tipos de pagamento</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie o primeiro tipo para começar a faturar.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Título</TableHead>
                    <TableHead>Troco</TableHead>
                    <TableHead>Tipo fiscal</TableHead>
                    <TableHead>Método no Vendus</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tipos.map((tipo) => (
                    <TableRow
                      key={tipo.id}
                      // O destaque acompanha o aviso do topo: a linha inteira
                      // muda de fundo, e não só um selo no meio da tabela. Pela
                      // MESMA regra do cartão (`naoEmite`) — se contam para o
                      // número, têm de se ver na tabela.
                      className={naoEmite(tipo) ? 'bg-destructive/5' : undefined}
                      data-testid={`pagamento-row-${tipo.id}`}
                    >
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          {tipo.nome}
                          {tipo.protegido && (
                            <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-label="Protegido" />
                          )}
                        </div>
                      </TableCell>
                      <TableCell>{trocoBadge(tipo.da_troco)}</TableCell>
                      <TableCell>
                        <span className="text-sm text-muted-foreground">
                          {codigosFiscais[tipo.tipo_fiscal] || tipo.tipo_fiscal}
                        </span>
                      </TableCell>
                      <TableCell>{celulaVendus(tipo)}</TableCell>
                      <TableCell>{estadoBadge(tipo.ativo)}</TableCell>
                      <TableCell className="text-right">
                        {tipo.protegido ? (
                          <div className="flex items-center justify-end">
                            <Button
                              variant="ghost"
                              size="icon"
                              title={AVISO_PROTEGIDO}
                              onClick={() => toast.info(AVISO_PROTEGIDO)}
                              data-testid={`locked-pagamento-${tipo.id}`}
                            >
                              <Lock className="h-4 w-4 text-muted-foreground" />
                            </Button>
                          </div>
                        ) : (
                          <div className="flex items-center justify-end gap-2">
                            <Button variant="ghost" size="icon" onClick={() => openEdit(tipo)} data-testid={`edit-pagamento-${tipo.id}`}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="icon" onClick={() => askDelete(tipo)} data-testid={`delete-pagamento-${tipo.id}`}>
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dialog criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto" data-testid="pagamento-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar tipo de pagamento' : 'Novo tipo de pagamento'}</DialogTitle>
            <DialogDescription>O nome é livre; o código fiscal é o que vai para o documento emitido no Vendus, e o método do Vendus é o que faz este tipo poder emitir.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="pagamento-nome">Nome *</Label>
                <Input
                  id="pagamento-nome"
                  value={form.nome}
                  onChange={(e) => setForm({ ...form, nome: e.target.value })}
                  placeholder="Ex: Glovo"
                  required
                  maxLength={60}
                  data-testid="pagamento-nome-input"
                />
                {fieldErrors.nome && <p className="text-xs text-destructive">{fieldErrors.nome}</p>}
              </div>
              <div className="space-y-2">
                <Label>Código fiscal *</Label>
                <Select value={form.tipo_fiscal} onValueChange={(v) => setForm({ ...form, tipo_fiscal: v })}>
                  <SelectTrigger data-testid="pagamento-tipo-fiscal-select"><SelectValue placeholder="Selecionar código fiscal" /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(codigosFiscais).map(([codigo, label]) => (
                      <SelectItem key={codigo} value={codigo}>{codigo} — {label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">É como este tipo é reportado ao fisco, independentemente do nome mostrado no balcão.</p>
              </div>

              {/* Método no Vendus — o campo sem o qual este tipo não emite */}
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <Label>Método no Vendus</Label>
                  {/* Onde estava o botão está agora o estado da leitura.

                      O botão saiu daqui: com a lista a reler-se sozinha ao ser
                      aberta, um botão neste sítio só podia ser carregado com a
                      lista fechada — e com a lista aberta, que é quando dava
                      jeito, o clique perdia-se na camada do popper sem deixar
                      rasto. Ficou só onde não há lista para abrir (ver
                      `explicarSemLista`).

                      A roda a girar aparece aqui E dentro da própria lista, e
                      não é repetição por descuido: o popper do Radix abre para
                      o lado onde houver espaço, e a 1280x720 este campo abre
                      PARA CIMA e tapa o cabeçalho. Cada uma das duas cópias é
                      a que se vê numa das direcções, e nunca há duas à vista
                      ao mesmo tempo com a lista aberta. Aqui é também a única
                      que se vê quando a leitura corre com a lista FECHADA (a
                      que arranca com o formulário). */}
                  {listaDisponivel && carregandoMetodos && (
                    <EstadoDaLeitura carregando lidaEm={lidaEm} testid="pagamento-metodos-estado" />
                  )}
                </div>

                {/* A ajuda que diz onde se criam os métodos vive AQUI, no
                    formulário, à vista, e já não no fim da lista.

                    No fim da lista ela só se via por sorte: a 1280x720 com 6
                    métodos, uma lista aberta para baixo mostrava 42px dos 78
                    do parágrafo — cortado precisamente antes do passo seguinte
                    — e a roda do rato não o desenrolava. A 1512x950 com 8
                    métodos via-se inteiro. Ou seja, a instrução de que o dono
                    precisa para acabar o trabalho aparecia-lhe ou não
                    consoante o tamanho do ecrã e o número de métodos da conta,
                    o que não é maneira nenhuma de dar uma instrução.

                    Aqui é texto do formulário: nasce e morre com o campo, não
                    tem altura limitada por popper nenhum e o diálogo desenrola-o
                    inteiro. A lista aberta pode passar-lhe por cima (a 1280x720
                    abre para cima e tapa-o), mas basta fechá-la — e fechá-la é
                    o que ele faz assim que desiste de procurar o método. Para
                    esse segundo, o topo da lista tem a versão curta. */}
                {listaDisponivel && (
                  <p className="text-xs text-muted-foreground" data-testid="pagamento-metodo-em-falta-ajuda">
                    <span className="font-medium text-foreground">Não encontra o método que precisa?</span>
                    {' '}{ONDE_CRIAR_O_METODO} {DEPOIS_DE_CRIAR}
                  </p>
                )}

                {listaDisponivel ? (
                  <Select
                    value={form.vendus_payment_method_id || SEM_METODO}
                    onValueChange={escolherMetodo}
                    // O coração da correcção: abrir a lista lê-a do Vendus.
                    //
                    // É o gesto que a pessoa ia fazer de qualquer maneira ao
                    // voltar do backoffice — e por isso não há nada de novo
                    // para aprender, nem botão nenhum para acertar. Os
                    // travões (uma leitura de cada vez, pausa mínima) estão no
                    // `carregarMetodos`; a escolha já feita não se perde
                    // enquanto a lista se relê, porque o `escolherMetodo`
                    // recusa tudo o que não seja uma escolha da pessoa.
                    onOpenChange={(aberta) => { if (aberta) carregarMetodos({ motivo: 'abertura' }); }}
                  >
                    <SelectTrigger data-testid="pagamento-metodo-vendus-select">
                      <SelectValue placeholder="Selecionar método do Vendus" />
                    </SelectTrigger>
                    <SelectContent>
                      {/* A PRIMEIRA linha da lista, e não a última: o fim é
                          exactamente o que se perde quando ela abre para baixo
                          num ecrã pequeno — foi o que aconteceu à ajuda que
                          aqui estava. O topo vê-se sempre.

                          É aqui que se vê que abrir a lista faz alguma coisa:
                          "A ler a lista do Vendus…" enquanto o pedido corre, e
                          a hora a mudar quando ele chega. Está sempre presente,
                          mesmo parada, de propósito — se só aparecesse durante
                          a leitura, os itens desciam meia linha por baixo de um
                          dedo já a caminho do clique.

                          Texto, não item: não há aqui nada para escolher, e um
                          item escolhível só gravaria lixo no campo.

                          A segunda linha é a versão curta da ajuda que está no
                          formulário, e existe por uma razão medida a correr o
                          ecrã: a 1280x720 esta lista ABRE PARA CIMA e tapa o
                          campo inteiro, ajuda incluída. Aqui dentro é o único
                          sítio que nenhuma das duas direcções tapa, e é onde
                          os olhos estão no segundo em que ele não encontra o
                          "MB Way". A frase inteira — onde criar e o que fazer
                          a seguir — fica no formulário, que é onde ele volta a
                          olhar assim que fecha a lista. */}
                      <div className="max-w-[calc(var(--radix-select-trigger-width)_-_0.5rem)] px-2 py-1.5 space-y-0.5" data-testid="pagamento-metodos-estado-lista">
                        <EstadoDaLeitura carregando={carregandoMetodos} lidaEm={lidaEm} />
                        <p className="text-xs leading-snug text-muted-foreground">
                          Só aparecem os métodos que já existem na conta Vendus.
                        </p>
                      </div>
                      <SelectSeparator />
                      <SelectItem value={SEM_METODO}>Sem método — este tipo não emite faturas</SelectItem>
                      {metodos.map((m) => (
                        <SelectItem key={comoTexto(m.id)} value={comoTexto(m.id)}>{rotuloMetodo(m)}</SelectItem>
                      ))}
                      {idOrfao && (
                        <SelectItem value={idOrfao}>#{idOrfao} — já não consta na conta Vendus</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                ) : (!jaLeuMetodos && carregandoMetodos) ? (
                  <Bloco tom="neutro" icone={RefreshCw} titulo="A ler a lista de métodos do Vendus…" testid="pagamento-metodos-a-carregar" />
                ) : (
                  <Bloco
                    tom={explicacaoSemLista.tom}
                    icone={AlertTriangle}
                    titulo={explicacaoSemLista.titulo}
                    testid="pagamento-metodos-indisponiveis"
                  >
                    <p className="text-muted-foreground">{explicacaoSemLista.corpo}</p>
                    <p>
                      {form.vendus_payment_method_id ? (
                        <>
                          Este tipo continua ligado ao método <span className="font-mono">#{form.vendus_payment_method_id}</span> e
                          guardar aqui <strong>não desfaz</strong> essa ligação — só não dá para a mudar sem a lista.
                        </>
                      ) : (
                        <>
                          Este tipo fica <strong>sem método do Vendus</strong> e não emite faturas. Pode guardar os
                          restantes campos e voltar cá quando a lista carregar.
                        </>
                      )}
                    </p>
                    {/* O botão vive DENTRO do bloco que explica a falha, e o
                        bloco não desaparece enquanto ele trabalha: a explicação
                        e o gesto que ela pede têm de estar à vista ao mesmo
                        tempo, sobretudo durante os até 20 s que o Vendus leva a
                        responder mal. Aqui o clique chega-lhe sempre — não há
                        lista aberta por cima, porque não há lista nenhuma. */}
                    {explicacaoSemLista.podeTentarDeNovo && (
                      <div className="pt-1">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => carregarMetodos({ motivo: 'pedido' })}
                          disabled={carregandoMetodos}
                          data-testid="recarregar-metodos-vendus-btn"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${carregandoMetodos ? 'animate-spin' : ''}`} />
                          {carregandoMetodos ? 'A ler a lista do Vendus…' : explicacaoSemLista.rotuloTentar}
                        </Button>
                      </div>
                    )}
                    {/* Ver o cartão da página: a mensagem técnica vem em
                        último e nunca sozinha. */}
                    {explicacaoSemLista.tecnico && (
                      <p className="text-xs text-muted-foreground border-t border-border/60 pt-1.5">
                        <span className="font-medium">Para quem for tratar disto:</span>{' '}
                        {explicacaoSemLista.tecnico}
                      </p>
                    )}
                  </Bloco>
                )}

                {!form.vendus_payment_method_id ? (
                  <Bloco tom="perigo" icone={Ban} titulo="Sem isto, este tipo de pagamento não emite faturas" testid="pagamento-sem-metodo-aviso">
                    <p className="text-muted-foreground">
                      No POS o botão aparece morto. Se a emissão chegar a ser tentada, o servidor
                      recusa-a com "{RECUSA_DO_SERVIDOR}" — com o cliente à frente e a venda por fechar.
                    </p>
                    {/* A frase do ONDE_CRIAR_O_METODO estava aqui também, e
                        saiu: agora vive por cima do campo, permanente, a três
                        linhas de distância. Repeti-la aqui era dizer a mesma
                        coisa duas vezes no mesmo palmo de ecrã, e uma coisa
                        dita duas vezes lê-se como duas coisas diferentes. */}
                  </Bloco>
                ) : fiscalDivergente ? (
                  <Bloco tom="aviso" icone={AlertTriangle} titulo="Os dois códigos fiscais não são o mesmo" testid="pagamento-fiscal-divergente-aviso">
                    <p className="text-muted-foreground">
                      Aqui está <strong>{form.tipo_fiscal}</strong>
                      {codigosFiscais[form.tipo_fiscal] ? ` (${codigosFiscais[form.tipo_fiscal]})` : ''}; no Vendus
                      este método é <strong>{metodoEscolhido.tipo_fiscal}</strong>
                      {codigosFiscais[metodoEscolhido.tipo_fiscal] ? ` (${codigosFiscais[metodoEscolhido.tipo_fiscal]})` : ''}.
                      O que sai na fatura é o do Vendus.
                    </p>
                    <p className="text-muted-foreground">
                      Não é necessariamente um erro — o "Uber" está mesmo assim de propósito. Nada é
                      corrigido automaticamente: se não era isto que queria, mude um dos lados.
                    </p>
                  </Bloco>
                ) : idOrfao ? (
                  <Bloco tom="aviso" icone={AlertTriangle} titulo="Este método já não consta na conta Vendus" testid="pagamento-metodo-orfao-aviso">
                    <p className="text-muted-foreground">
                      O id <span className="font-mono">#{idOrfao}</span> está guardado mas não veio na lista — foi
                      apagado ou a conta é outra. A emissão vai ser recusada do lado do Vendus. Escolha um
                      método da lista.
                    </p>
                  </Bloco>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label>Dá troco? *</Label>
                <RadioGroup
                  value={form.da_troco === null ? undefined : (form.da_troco ? 'sim' : 'nao')}
                  onValueChange={(v) => setForm({ ...form, da_troco: v === 'sim' })}
                  className="flex items-center gap-6"
                  data-testid="pagamento-da-troco-radio"
                >
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="sim" id="da-troco-sim" />
                    <Label htmlFor="da-troco-sim" className="cursor-pointer font-normal">Sim</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="nao" id="da-troco-nao" />
                    <Label htmlFor="da-troco-nao" className="cursor-pointer font-normal">Não</Label>
                  </div>
                </RadioGroup>
                <p className="text-xs text-muted-foreground">Só faz sentido em dinheiro. Marcar "Sim" num pagamento eletrónico faz o POS pedir troco por engano no balcão.</p>
              </div>
              <div className="grid grid-cols-2 gap-4 items-end">
                <div className="space-y-2">
                  <Label htmlFor="pagamento-ordem">Ordem</Label>
                  <Input
                    id="pagamento-ordem"
                    type="number"
                    value={form.ordem}
                    onChange={(e) => setForm({ ...form, ordem: e.target.value })}
                    data-testid="pagamento-ordem-input"
                  />
                </div>
                <div className="flex items-center gap-2 pb-2.5">
                  <Switch id="pagamento-ativo" checked={form.ativo} onCheckedChange={(v) => setForm({ ...form, ativo: v })} data-testid="pagamento-ativo-switch" />
                  <Label htmlFor="pagamento-ativo" className="cursor-pointer">Ativo</Label>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-pagamento-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar tipo de pagamento</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.nome}"? Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
