import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, AlertTriangle, HelpCircle, CheckCircle2, ShieldAlert, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import PosCampoValor from './PosCampoValor';
import {
  fecharCaixa, getContasAbertasDaCaixa, detalhesErroPos, temMaisDe2CasasDecimaisPos,
} from '@/lib/pos';

const euros = (valor) => `€ ${(Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function LinhaValor({ label, valor, destaque }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className={destaque ? 'font-heading font-bold text-lg' : 'font-medium'}>{valor}</span>
    </div>
  );
}

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

  // As duas famílias. `trava_o_fecho === true` de propósito, e não a verdade
  // genérica do JavaScript: uma resposta de um servidor anterior a este campo
  // não pode passar a dizer que TODAS as contas travam o fecho — era a mesma
  // frase errada, só que ao contrário e mais assustadora.
  const travam = todas.filter((c) => c.trava_o_fecho === true);
  const porCobrar = todas.filter((c) => c.trava_o_fecho !== true);
  const noutroPosto = porCobrar.filter((c) => !destePosto(c, contas));
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
            <span className="tabular-nums">{euros(totalPorCobrar)}</span>.
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
      <DialogContent className="max-w-md">
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
            <div className="divide-y">
              <LinhaValor label="Fundo de abertura" valor={euros(resultado.fundo)} />
              <LinhaValor label="Vendas em dinheiro" valor={euros(resultado.vendas_dinheiro)} />
              <LinhaValor label="Entradas" valor={euros(resultado.entradas)} />
              <LinhaValor label="Saídas" valor={euros(resultado.saidas)} />
              <LinhaValor label="Esperado" valor={euros(resultado.esperado)} destaque />
              <LinhaValor label="Contado" valor={euros(resultado.contado)} destaque />
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
