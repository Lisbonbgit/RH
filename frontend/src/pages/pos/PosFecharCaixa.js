import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, AlertTriangle, HelpCircle, CheckCircle2, ShieldAlert, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import PosCampoValor from './PosCampoValor';
// O `euros` e o `LinhaValor` vivem no PosResumoDoTurno e vêm de lá — eram
// duas cópias do mesmo desenho, e o Z e o Ponto de Caixa mostram agora os
// mesmos números lado a lado: dois desenhos a divergir seriam a mesma
// informação a parecer duas coisas diferentes.
import PosResumoDoTurno, { euros, LinhaValor } from './PosResumoDoTurno';
import {
  fecharCaixa, getContasAbertasDaCaixa, detalhesErroPos, temMaisDe2CasasDecimaisPos,
} from '@/lib/pos';

// Quantas contas deste turno ficam por cobrar, e quanto valem.
//
// **A faixa do balcão prometia isto e o fecho não cumpria.** Por cima das
// partes de uma conta repartida lia-se "enquanto não forem cobradas ou
// canceladas, ficam abertas no servidor e o fecho desta caixa vai contá-las" —
// e o Z lia só as vendas `emitida`. Uma conta dividida por duas pessoas e
// cobrada a nenhuma: a caixa fechava, o Z saía sem uma palavra sobre os
// 14,10 €, e não havia relatório nenhum onde eles aparecessem.
//
// **DUAS famílias, e não uma — o defeito desta ronda.** A caixa de aviso
// afirmava, sobre TODAS as contas listadas, "Não impedem o fecho". Medido no
// browser: o diálogo listou 2 partes e uma conta travada, e carregar em Fechar
// Caixa devolveu 409 por causa da travada. Uma conta com RESERVA FISCAL viva
// impede mesmo o fecho (`caixa.py::_venda_com_emissao_viva`) — e está certo
// que impeça: fechar a caixa a meio de uma emissão é fechar as contas antes de
// o dinheiro estar contado. O que estava errado era a frase. Quem decide é o
// `trava_o_fecho` que o servidor manda por conta, nunca uma regra escrita aqui.
//
// **E de que POSTO é cada uma — o outro defeito.** A lista é do âmbito da
// SESSÃO (bem: é o turno inteiro que se está a fechar), mas todas as acções
// deste ecrã são do âmbito do DISPOSITIVO — `GET /pos/venda/repartidas` filtra
// pelo `dispositivo_id` do token. Medido: dois postos na mesma caixa, o
// Drive-Thru divide a conta dele e não cobra ninguém; o fecho pedido do Balcão
// listava as três contas do turno (28,20 €) e mandava-a cobrá-las, e o ecrã do
// Balcão respondia `0 grupos`. A operadora lia uma instrução que não conseguia
// cumprir. **Não se alarga o âmbito das acções** — uma operadora a cobrar a
// conta do outro posto é outro problema, e pior. Alarga-se o que o texto DIZ:
// quais são deste posto, quais são de outro, e o que ela pode fazer a cada um.
//
// **Nada disto trava o fecho por nossa conta** (regra 3 do dono: uma parte que
// ninguém vai pagar prenderia a loja para sempre) — mostra-se ANTES da
// contagem, enquanto ainda dá para ir cobrar ou cancelar, e escreve-se no Z
// para quem o ler amanhã.
//
// `momento` muda a moldura E o que se pode fazer: 'antes' é um aviso que ainda
// dá para atender; 'z' é o registo do que ficou mesmo por cobrar quando o
// turno fechou — a partir daí o ecrã não alcança nenhuma delas (nem este nem
// nenhum outro do POS), e quem as resolve é o gestor, no backoffice, na mesma
// lista das reservas fiscais presas.

// Esta conta está ao alcance DESTE posto? A comparação é a mesma que o
// servidor faz em `GET /pos/venda/repartidas` e `GET /pos/venda/aberta`
// (`dispositivo_id` do token), por isso responde exactamente o que o ecrã vai
// conseguir ir buscar. Dois `undefined` (um servidor anterior a este campo,
// ou um token antigo sem dispositivo) comparam iguais — e está certo: nesse
// âmbito as contas são todas do mesmo lado, tal como no filtro do servidor.
const destePosto = (conta, contas) => conta.dispositivo_id === contas.dispositivo_id;

// O nome do posto para escrever à vista. Sem nome (o PC foi revogado desde
// então) não se inventa nenhum — "outro posto" é a verdade que se sabe.
const nomeDoPosto = (conta) => conta.dispositivo_nome || 'outro posto';

// **A conta que o BALCÃO não consegue tocar.** O servidor manda o estado em que
// a venda ficou (`estado_da_venda`) e o motivo por que ela está por resolver
// (`motivo`, ver `por_resolver.py`). Uma que não esteja `aberta` — uma mãe
// `separada` a quem a divisão morreu a meio, um estado que o servidor ainda não
// conhece — não se cobra nem se cancela no POS: as escritas respondem 409 e ela
// não aparece em ecrã nenhum de onde se lhe possa pegar. Mandar a operadora
// "cobrá-la ou cancelá-la" era pedir-lhe o que a rota recusa, que é o beco que
// esta ronda inteira persegue.
//
// A comparação é com `!= null` primeiro, e é deliberado: uma resposta de um
// servidor anterior a este campo não pode passar a dizer que NENHUMA das contas
// se cobra — era a mesma frase errada, só que ao contrário.
const foraDoAlcanceDoBalcao = (c) =>
  c.estado_da_venda != null && c.estado_da_venda !== 'aberta';

function ListaDeContas({ contas, linhas, mostrarPosto }) {
  return (
    <ul className="space-y-1 pl-6">
      {linhas.map((c) => (
        <li key={c.id} className="flex items-baseline justify-between gap-2">
          <span className="font-mono text-[11px] break-all select-all">
            {c.id}
            {/* `break-normal` a desfazer o `break-all` do id: o `break-all`
                existe para o uuid poder partir em qualquer sítio, e sem isto
                partia também o nome do posto ao meio ("só no P / C
                Drive-Thru"), que foi como isto apareceu no browser. */}
            {c.conta_mae_id && (
              <span className="ml-1 font-sans italic break-normal">(parte de uma conta repartida)</span>
            )}
            {/* A que não se cobra nem se cancela aqui, marcada na própria
                linha — como a parte de uma conta repartida. */}
            {foraDoAlcanceDoBalcao(c) && (
              <span className="ml-1 font-sans italic break-normal">
                {c.motivo === 'mae_separada_sem_partes'
                  ? '(conta repartida sem partes — não se cobra no balcão)'
                  : '(não se cobra no balcão)'}
              </span>
            )}
            {/* De que posto é. Só quando há mesmo mais do que um em jogo —
                numa loja com um PC só, dizer "neste posto" em todas as
                linhas era ruído a competir com o que interessa. */}
            {mostrarPosto && !destePosto(c, contas) && (
              <span className="ml-1 font-sans italic break-normal">— só no {nomeDoPosto(c)}</span>
            )}
          </span>
          <span className="tabular-nums shrink-0">
            {c.total == null ? '—' : euros(c.total)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Bloco({ tom, icone, children }) {
  const fundo = tom === 'trava'
    ? 'bg-destructive/10 text-destructive'
    : (tom === 'aviso' ? 'bg-warning/10 text-warning' : 'bg-muted');
  return (
    <div className={`rounded-lg p-3 text-sm space-y-2 ${fundo}`}>
      <div className="flex items-start gap-2">
        {icone}
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}

function ContasPorCobrar({ contas, momento }) {
  if (!contas || !contas.quantas) return null;
  const antes = momento === 'antes';
  const todas = contas.contas || [];

  // As TRÊS famílias. `trava_o_fecho === true` e `entregue_ao_gestor === true`
  // de propósito, e não a verdade genérica do JavaScript: uma resposta de um
  // servidor anterior a estes campos não pode passar a dizer que TODAS as
  // contas travam o fecho, nem que são todas do gestor — era a mesma frase
  // errada, só que ao contrário e mais assustadora.
  const travam = todas.filter((c) => c.trava_o_fecho === true);
  // **A conta ENTREGUE AO GESTOR, e porque é que ela precisa de família
  // própria.** Chegava aqui com `trava_o_fecho: false` (o gestor já libertou a
  // reserva dela) e caía no monte do "por cobrar", debaixo de uma frase que
  // manda «cobre-as antes de fechar; se ninguém pagar, cancele-as». Nenhuma
  // das duas saídas é executável: as escritas do balcão recusam-na
  // (`venda.py::_garante_do_balcao`) e ela não aparece em ecrã nenhum do POS
  // de onde se lhe possa tocar (`venda.py::_contas_do_balcao` exclui-a). O
  // servidor sempre mandou a marca — `entregue_ao_gestor` —, e este ecrã nunca
  // a desenhou. Pedir à operadora o que a rota recusa é o mesmo beco que esta
  // ronda inteira persegue, e aqui custava-lhe uma tentativa e um telefonema.
  const doGestor = todas.filter(
    (c) => c.trava_o_fecho !== true && c.entregue_ao_gestor === true);
  const porCobrar = todas.filter(
    (c) => c.trava_o_fecho !== true && c.entregue_ao_gestor !== true);
  const noutroPosto = porCobrar.filter((c) => !destePosto(c, contas));
  const foraDoAlcance = porCobrar.filter(foraDoAlcanceDoBalcao);
  // O euro desta caixa vem SOMADO DO SERVIDOR (`total_por_cobrar`), e não de
  // um `reduce` sobre a lista: é a regra 1 do cabeçalho do PosVenda — o ecrã
  // nunca soma dinheiro. Somar aqui juntava-lhe ainda os erros da vírgula
  // flutuante binária do JavaScript, sobre números que o servidor já tinha
  // fechado ao cêntimo.
  //
  // O recuo para `total` não é decoração: um servidor anterior a esta ronda
  // não manda `trava_o_fecho` nenhum, por isso `travam` fica vazio e ESTA
  // família é a lista toda — que é exactamente o que `total` soma. Sem o
  // recuo, esse servidor punha "€ 0,00" por cima de uma lista com contas lá
  // dentro, que é a pior das mentiras possíveis num ecrã de fecho.
  const totalPorCobrar = contas.total_por_cobrar ?? contas.total;
  // Os euros das outras duas caixas: o servidor manda os subtotais
  // já somados (`total_por_cobrar` é tudo o que não trava; `total_do_balcao` e
  // `total_do_gestor` são as duas metades dele), e é de lá que saem — nunca de
  // um `reduce` aqui, que era pôr o JavaScript a fazer aritmética de dinheiro
  // sobre números que o servidor já fechou ao cêntimo.
  //
  // Sem `total_do_gestor` na resposta (um servidor anterior a esta ronda), a
  // família do gestor vem vazia — `entregue_ao_gestor` também não vinha — e o
  // recuo do balcão para `total_por_cobrar` continua exacto.
  const totalDoGestor = contas.total_do_gestor;
  // E o do BALCÃO — a família de cima sem as do gestor. Recuo para
  // `total_por_cobrar` quando o servidor é anterior a esta ronda: aí a família
  // do gestor vem vazia (`entregue_ao_gestor` também não vinha) e os dois
  // números são o mesmo, por isso o recuo continua exacto.
  const totalDoBalcao = contas.total_do_balcao ?? totalPorCobrar;

  return (
    <div className="space-y-2">
      {/* A que IMPEDE o fecho vem primeiro, e sozinha: é a única desta lista
          sobre a qual carregar em Fechar Caixa devolve um erro, e a operadora
          tem de a distinguir das outras antes de tentar. */}
      {travam.length > 0 && (
        <Bloco tom="trava" icone={<ShieldAlert className="h-4 w-4 shrink-0 mt-0.5" />}>
          <p className="font-medium">
            {travam.length === 1
              ? '1 conta IMPEDE o fecho desta caixa'
              : `${travam.length} contas IMPEDEM o fecho desta caixa`}.
          </p>
          <p className="mt-1">
            {travam.length === 1
              ? 'Tem uma emissão de fatura por confirmar'
              : 'Têm uma emissão de fatura por confirmar'}
            {antes
              ? ' — enquanto estiver assim, carregar em Fechar Caixa devolve um erro. Não se cobra nem se cancela no balcão: é o gestor que a resolve, na lista de reservas fiscais presas do backoffice. Dê-lhe esta referência:'
              : ' e só o gestor as resolve, na lista de reservas fiscais presas do backoffice. Referência:'}
          </p>
          <ListaDeContas contas={contas} linhas={travam} mostrarPosto={false} />
        </Bloco>
      )}

      {porCobrar.length > 0 && (
        <Bloco
          tom={antes ? 'aviso' : 'neutro'}
          icone={antes
            ? <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            : <Users className="h-4 w-4 shrink-0 mt-0.5" />}
        >
          <p className="font-medium">
            {porCobrar.length === 1
              ? '1 conta fica por cobrar neste turno'
              : `${porCobrar.length} contas ficam por cobrar neste turno`}
            {' — '}
            <span className="tabular-nums">{euros(totalDoBalcao)}</span>.
          </p>
          <p className={antes ? 'mt-1' : 'mt-1 text-muted-foreground'}>
            {antes
              ? 'Não impedem o fecho, mas não entram no Z como vendas: esse dinheiro não foi facturado nem entrou na gaveta.'
              : 'Não foram facturadas nem entraram na gaveta. Ficam registadas neste Z e continuam abertas no servidor.'}
            {' '}
            {/* O que ela pode MESMO fazer, e nada mais. Este ecrã só alcança
                as contas deste posto; mandá-la cobrar as do outro era pedir-
                lhe uma coisa que o servidor não lhe deixa fazer daqui. */}
            {antes
              ? (noutroPosto.length === 0
                ? 'Se ainda houver quem pague, cobre-as antes de fechar; se ninguém pagar, cancele-as. O Z regista o que ficar.'
                : (noutroPosto.length === porCobrar.length
                  ? `Nenhuma delas foi aberta neste PC, e este ecrã não lhes chega — quem as cobra ou cancela é o posto onde foram abertas (${nomeDoPosto(noutroPosto[0])}), antes de fechar. O Z regista o que ficar.`
                  : 'As deste PC ainda dá para cobrar ou cancelar aqui, antes de fechar; as que dizem outro posto só se resolvem no PC onde foram abertas — este ecrã não lhes chega. O Z regista o que ficar.'))
              : 'Quem as resolve agora é o gestor, no backoffice — aparecem na mesma lista das reservas fiscais presas, já com o turno em que ficaram.'}
          </p>
          {/* E a ressalva, quando há alguma que ela não consegue tocar: a
              instrução de cima ("cobre-as ou cancele-as") não vale para essas,
              e dizê-lo é a diferença entre uma tentativa e um telefonema. */}
          {antes && foraDoAlcance.length > 0 && (
            <p className="mt-1">
              {foraDoAlcance.length === porCobrar.length
                ? 'Nenhuma delas se cobra nem se cancela no balcão'
                : 'As marcadas «não se cobra no balcão» não se cobram nem se cancelam aqui'}
              {' — o POS recusa, e elas não aparecem em ecrã nenhum de onde lhes '}
              {'possa pegar. Ficam registadas neste Z como dinheiro por receber e '}
              {'é o gestor que as resolve, no backoffice (Contas por Resolver).'}
            </p>
          )}
          {/* A referência de cada uma, à vista e seleccionável: é o que a
              operadora diz ao gestor, e é por ela que ele as encontra. As que
              nasceram de uma conta repartida dizem-no — "faltou cobrar uma
              pessoa" e "ficou uma conta a meio" são duas conversas
              diferentes. */}
          <ListaDeContas
            contas={contas}
            linhas={porCobrar}
            mostrarPosto={noutroPosto.length > 0}
          />
        </Bloco>
      )}

      {/* A que JÁ É DO GESTOR. Não trava o fecho e não é para cobrar aqui: a
          operadora entregou-a («Servir o cliente seguinte») e a partir daí é
          ele que a resolve, no backoffice. A única coisa que este ecrã lhe
          deve é dizer isso — e a referência, que é o que ela lhe dá ao
          telefone. */}
      {doGestor.length > 0 && (
        <Bloco tom="neutro" icone={<Users className="h-4 w-4 shrink-0 mt-0.5" />}>
          <p className="font-medium">
            {doGestor.length === 1
              ? '1 conta já foi entregue ao gestor'
              : `${doGestor.length} contas já foram entregues ao gestor`}
            {totalDoGestor != null && (
              <>
                {' — '}
                <span className="tabular-nums">{euros(totalDoGestor)}</span>
              </>
            )}.
          </p>
          <p className="mt-1 text-muted-foreground">
            {antes
              ? 'Não impedem o fecho e não são para cobrar nem cancelar aqui — saíram do balcão e é o gestor que as resolve, no backoffice. Ficam registadas no Z como dinheiro por receber. Referência:'
              : 'Ficam registadas neste Z como dinheiro por receber e é o gestor que as resolve, no backoffice. Referência:'}
          </p>
          <ListaDeContas contas={contas} linhas={doGestor} mostrarPosto={false} />
        </Bloco>
      )}
    </div>
  );
}

// Fechar a caixa e o relatório Z (Task 2, spec §7.6). Regra 3 do dono: o
// fecho NUNCA bloqueia por a contagem não bater, nem por a verificação
// contra o Vendus falhar — os dois casos só mostram um aviso, a funcionária
// segue para casa à mesma. Duas etapas: contar (envia `contado`) e depois
// o resultado (o que o servidor devolveu, incluindo o Z) — nunca calculado
// aqui, sempre o número que veio de faturacao/caixa.py::fechar_caixa.
export default function PosFecharCaixa({ aberto, onFechar, caixa, sessao, onFechado }) {
  const [contado, setContado] = useState('');
  const [aEnviar, setAEnviar] = useState(false);
  const [resultado, setResultado] = useState(null);
  // O que fica por cobrar: `null` enquanto se pergunta, `{ quantas, total,
  // contas }` depois, e `{ erro: '…' }` se a pergunta falhou. Os três estados
  // são distintos de propósito — "ainda não sei" e "não ficou nada" não podem
  // desenhar-se da mesma maneira num ecrã que fala de dinheiro por receber.
  const [porCobrar, setPorCobrar] = useState(null);

  useEffect(() => {
    if (!aberto) return undefined;
    setContado('');
    setResultado(null);
    setPorCobrar(null);
    // Perguntado à ABERTURA do diálogo, e não uma vez ao montar o ecrã: entre
    // a operadora abrir a app e vir fechar a caixa passa um turno inteiro, e
    // o que interessa é o que está aberto AGORA. É a leitura de
    // `GET /pos/caixa/contas-abertas` — só leitura, nunca fecha nada.
    let vivo = true;
    getContasAbertasDaCaixa(caixa.id)
      .then(({ data }) => { if (vivo) setPorCobrar(data || { quantas: 0, total: 0, contas: [] }); })
      .catch((error) => {
        // Falhar aqui não pode impedir o fecho (regra 3 do dono) — mas
        // também não se finge que não ficou nada por cobrar. Diz-se que não
        // se sabe, e o Z que sai a seguir traz a lista à mesma, essa
        // calculada pelo servidor no momento do fecho.
        if (vivo) {
          setPorCobrar({
            erro: detalhesErroPos(
              error, 'Não foi possível saber que contas ficam por cobrar.',
            ).mensagem,
          });
        }
      });
    return () => { vivo = false; };
  }, [aberto, caixa.id]);

  const podeFechar = contado !== '' && !temMaisDe2CasasDecimaisPos(contado) && Number(contado) >= 0 && !aEnviar;

  const confirmarContagem = async () => {
    if (!podeFechar) return;
    setAEnviar(true);
    try {
      const { data } = await fecharCaixa({ caixa_id: caixa.id, contado: Number(contado) });
      setResultado(data);
    } catch (error) {
      const { mensagem } = detalhesErroPos(error, 'Não foi possível fechar a caixa.');
      toast.error(mensagem);
    } finally {
      setAEnviar(false);
    }
  };

  const concluir = () => {
    setResultado(null);
    onFechado();
  };

  return (
    <Dialog open={aberto} onOpenChange={(v) => { if (!v && !resultado) onFechar(); }}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        {!resultado ? (
          <>
            <DialogHeader><DialogTitle>Fechar Caixa</DialogTitle></DialogHeader>
            <p className="text-sm text-muted-foreground">
              Conte o dinheiro na gaveta e introduza o montante contado. O esperado e a
              diferença aparecem a seguir — a contagem nunca impede o fecho.
            </p>
            {/* ANTES do campo da contagem, e não depois: é a última
                oportunidade de ir cobrar ou cancelar uma conta que ficou
                aberta, e uma vez assinado o Z não há volta atrás. */}
            {porCobrar === null && (
              <div className="flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                <span>A ver que contas ficam por cobrar…</span>
              </div>
            )}
            {porCobrar?.erro && (
              <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{porCobrar.erro} O Z que sai a seguir traz a lista à mesma.</span>
              </div>
            )}
            <ContasPorCobrar contas={porCobrar} momento="antes" />
            <div className="py-2">
              <PosCampoValor id="contado-fecho" label="Montante contado" valor={contado} onChange={setContado} autoFocus disabled={aEnviar} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={onFechar} disabled={aEnviar}>Cancelar</Button>
              <Button onClick={confirmarContagem} disabled={!podeFechar}>
                {aEnviar ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Fechar Caixa'}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader><DialogTitle>Relatório Z</DialogTitle></DialogHeader>

            {/* O mesmo bloco que a operadora já viu no Ponto de Caixa a meio
                da tarde — movimentos do turno, desdobramento por tipo de
                pagamento e mapa de imposto — desenhado pelo MESMO componente
                sobre os números da MESMA função do servidor
                (`caixa._resumo_do_turno`).

                O desdobramento por tipo de pagamento é o que faltava aqui: o
                Z dava o total em dinheiro e mais nada, e ao fechar ninguém
                conseguia bater o rolo do terminal de Multibanco nem o
                extracto do Glovo contra o turno — o gestor fechava o mês a
                somar à mão. O mapa de imposto é o que a contabilista pede, e
                a esta hora as vendas do turno já não mudam.

                O que o Z tem a mais, e o Ponto de Caixa não pode ter, é a
                contagem: o contado e a diferença. */}
            <PosResumoDoTurno resumo={resultado} />

            <div className="divide-y">
              <LinhaValor label="Contado na gaveta" valor={euros(resultado.contado)} destaque />
              <LinhaValor
                label="Diferença"
                valor={`${resultado.diferenca > 0 ? '+' : ''}${euros(resultado.diferenca)}`}
                destaque
              />
            </div>

            <Separator />

            {/* O que ficou por cobrar, agora com o número definitivo do
                servidor — calculado depois da marca `a_fechar`. E "definitivo"
                é uma palavra que este comentário passou duas rondas a afirmar
                sem direito: dizia-se aqui que a partir da marca "mais nenhuma
                conta pode nascer nesta sessão", e isso era verdade só sobre o
                `abrir_venda`. Medido pelas rotas reais, o `dividir` fazia
                nascer partes numa sessão em `a_fechar` e o `linhas` fazia uma
                conta subir de 14,10 € para 21,15 € depois do Z assinado. São
                três guardas do servidor que o tornam definitivo hoje, e estão
                listadas uma a uma em `caixa.py::fechar_caixa` — este número
                vale o que valerem elas, e não o que este comentário disser.
                Fica também gravado na sessão, para o gestor o encontrar dias
                depois — no backoffice, na lista das reservas fiscais
                presas, que é para onde estas contas passam a ir quando o
                turno fecha. */}
            <ContasPorCobrar contas={resultado.contas_abertas} momento="z" />

            {resultado.verificacao_vendus?.aviso && (
              <div className="flex items-start gap-2 rounded-lg bg-warning/10 text-warning p-3 text-sm">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{resultado.verificacao_vendus.aviso}</span>
              </div>
            )}
            {resultado.verificacao_vendus?.nao_verificado && (
              <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>Não foi possível verificar contra o Vendus. {resultado.verificacao_vendus.nao_verificado}</span>
              </div>
            )}
            {!resultado.verificacao_vendus && (
              <div className="flex items-start gap-2 rounded-lg bg-success/10 p-3 text-sm">
                <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-success" />
                <span>Confere com o Vendus.</span>
              </div>
            )}

            <DialogFooter>
              <Button className="w-full h-12" onClick={concluir}>Concluir</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
