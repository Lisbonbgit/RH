import React, { useCallback, useEffect, useState } from 'react';
import {
  getDefinicoesPlataformas, gravarDefinicoesPlataformas, getRelatorioPlataformas,
  getHistoricoPlataformas, recolherPlataformasAgora, enviarPlataformasAgora,
  detalhesErro, euros, diaCurto, intervalo, quandoPaga,
} from '../../../lib/plataformas';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Switch } from '../../../components/ui/switch';
import { Alert, AlertDescription } from '../../../components/ui/alert';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '../../../components/ui/table';
import {
  Bike, Mail, Plus, Trash2, Send, Clock, Loader2, RefreshCw, AlertTriangle,
  TrendingUp, TrendingDown, CalendarClock, Store,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// A mesma regra do servidor (`DefinicoesEntrada.emails`), mas só para avisar
// ANTES de gravar — quem decide é o servidor. Um endereço inválido faz o
// Resend recusar o envio INTEIRO, e o relatório de segunda não sai para
// ninguém, não só para quem se enganou a escrever.
const PARECE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

const NOMES = { uber: 'Uber Eats', bolt: 'Bolt Food', glovo: 'Glovo' };

/**
 * ▲ 12,3% / ▼ 4,5% — ou a razão por que não se compara.
 *
 * **«Sem semana anterior para comparar» só se pode escrever quando ela não
 * existe.** Quando existe e a comparação é que não é honesta (faltou o
 * relatório de uma loja, e três lojas contra quatro medem o relatório que
 * faltou e não as vendas), a frase tem de ser outra — as duas significam
 * coisas diferentes para quem lê.
 */
function Variacao({ valor, termo, houveAnterior }) {
  if (valor === null || valor === undefined) {
    return (
      <span className="text-xs text-muted-foreground">
        {houveAnterior
          ? 'comparação suspensa — mudaram as lojas que reportaram'
          : `sem ${termo} para comparar`}
      </span>
    );
  }
  const sobe = valor >= 0;
  const Icone = sobe ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold ${
      sobe ? 'text-emerald-600' : 'text-destructive'}`}>
      <Icone className="h-3.5 w-3.5" />
      {Math.abs(valor).toFixed(2).replace('.', ',')}% vs. {termo}
    </span>
  );
}

/**
 * Um cartão por plataforma. **Um relatório em falta não mostra números.**
 * O ecrã diz o que falta e mantém a data de pagamento (que é do calendário e
 * não depende de email nenhum) — nunca um zero, que se leria como «não
 * vendemos nada».
 */
function CartaoPlataforma({ linha }) {
  const { periodo, valores, estado } = linha;
  const lido = estado === 'lido';
  const quantas = linha.lojas_que_reportaram || 0;
  const termo = linha.ritmo === 'semana' ? 'semana anterior' : 'quinzena anterior';

  return (
    <Card data-testid={`plataforma-${linha.chave}`}>
      <CardContent className="p-4 sm:p-5 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <p className="font-heading font-bold text-lg leading-none">{linha.nome}</p>
          <span className="text-xs text-muted-foreground whitespace-nowrap pt-1">
            {intervalo(periodo.inicio, periodo.fim)}
          </span>
        </div>

        {lido ? (
          <>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
                A receber
                {/* De quantas lojas é este número. As plataformas mandam um
                    relatório por loja, e a soma de três não é a mesma coisa
                    que a soma de quatro. */}
                {quantas > 0 && (
                  <span className="normal-case tracking-normal font-normal">
                    {' · '}{quantas} loja{quantas === 1 ? '' : 's'}
                  </span>
                )}
              </p>
              <p className="text-2xl font-heading font-bold mt-0.5">
                {euros(valores.liquido)}
              </p>
              <p className="text-sm text-muted-foreground mt-0.5">
                {valores.pedidos === null || valores.pedidos === undefined
                  ? 'n.º de pedidos não indicado'
                  : `${valores.pedidos} pedido${valores.pedidos === 1 ? '' : 's'}`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-xs font-semibold text-primary">
                {quandoPaga(periodo)}
              </span>
              <Variacao valor={linha.variacao} termo={termo}
                houveAnterior={linha.anterior?.liquido !== null
                  && linha.anterior?.liquido !== undefined} />
            </div>

            {(valores.comissao !== null || valores.taxas !== null
              || valores.ajustes !== null) && (
              <div className="border-t pt-3 space-y-1.5">
                {[['Vendas (bruto)', valores.bruto], ['Comissão', valores.comissao],
                  ['Outras taxas', valores.taxas], ['Ajustes e estornos', valores.ajustes]]
                  .filter(([, v]) => v !== null && v !== undefined)
                  .map(([rotulo, v]) => (
                    <div key={rotulo} className="flex justify-between gap-3 text-sm">
                      <span className="text-muted-foreground">{rotulo}</span>
                      <span className="font-semibold">{euros(v)}</span>
                    </div>
                  ))}
              </div>
            )}

            {(linha.lojas || []).length > 0 && (
              <div className="border-t pt-3 space-y-1.5">
                <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
                  Por loja
                </p>
                {linha.lojas.map((loja) => (
                  <div key={loja.nome} className="flex justify-between gap-3 text-sm">
                    <span className="flex items-center gap-1.5 min-w-0">
                      <Store className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <span className="truncate">{loja.nome}</span>
                    </span>
                    <span className="font-semibold whitespace-nowrap">
                      {euros(loja.liquido)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {linha.origem?.assunto && (
              <p className="text-xs text-muted-foreground border-t pt-3">
                Lido do email «{linha.origem.assunto}»
                {linha.origem.data ? ` de ${diaCurto(linha.origem.data)}` : ''}
                {linha.periodo_origem === 'calendário'
                  ? ' · período deduzido do calendário' : ''}
              </p>
            )}
          </>
        ) : (
          /* **Dois estados diferentes, e nenhum deles é zero.** «Não recebido»
             é não ter chegado nada; «sem valores» é ter chegado e nós não
             termos conseguido ler — e é essa a diferença que diz a quem lê se
             vale a pena ir procurar ao portal da plataforma. */
          <div className="rounded-md bg-amber-50 dark:bg-amber-950/30 p-3 space-y-1">
            <p className="text-sm font-semibold text-amber-700 dark:text-amber-400">
              {estado === 'sem_valores'
                ? 'Relatório recebido, sem valores'
                : 'Relatório não recebido'}
            </p>
            <p className="text-sm text-muted-foreground">
              {estado === 'sem_valores'
                ? `Chegaram ${quantas} relatório${quantas === 1 ? '' : 's'} de ${
                  intervalo(periodo.inicio, periodo.fim)}, mas não foi possível ler `
                  + 'deles nenhum valor. Os números estão no portal da plataforma — '
                  + 'aqui ficam por saber, e não são zero.'
                : `Não chegou à caixa nenhum email com o relatório de ${
                  intervalo(periodo.inicio, periodo.fim)}. Os valores ficam por `
                  + 'saber — não são zero.'}
            </p>
            <p className="text-xs text-muted-foreground pt-1">
              {quandoPaga(periodo, false)}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function Plataformas() {
  const [relatorio, setRelatorio] = useState(null);
  const [historico, setHistorico] = useState([]);
  const [emails, setEmails] = useState([]);
  const [ativo, setAtivo] = useState(true);
  const [novo, setNovo] = useState('');
  const [erroNovo, setErroNovo] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [recolhendo, setRecolhendo] = useState(false);
  const [enviando, setEnviando] = useState(false);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const [rel, hist, def] = await Promise.all([
        getRelatorioPlataformas(), getHistoricoPlataformas(), getDefinicoesPlataformas(),
      ]);
      setRelatorio(rel.data);
      setHistorico(hist.data.registos || []);
      setEmails(def.data.emails || []);
      setAtivo(def.data.ativo !== false);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível carregar as plataformas.').mensagem);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  // Grava a lista INTEIRA de uma vez (é o que o PUT do servidor recebe) e
  // recebe por parâmetro o que vai gravar em vez de o ler do estado: um
  // `setEmails` seguido de `gravar()` gravava a lista ANTERIOR, porque o
  // estado do React só chega no render seguinte.
  const gravar = async (novosEmails, novoAtivo) => {
    setSaving(true);
    try {
      await gravarDefinicoesPlataformas({ emails: novosEmails, ativo: novoAtivo });
      setEmails(novosEmails);
      setAtivo(novoAtivo);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível gravar.').mensagem);
      // Volta ao que o servidor tem: deixar o ecrã a mostrar uma lista que não
      // ficou gravada é a pior das duas mentiras possíveis aqui.
      carregar();
    } finally {
      setSaving(false);
    }
  };

  const juntar = async () => {
    const email = novo.trim().toLowerCase();
    if (!email) return;
    if (!PARECE_EMAIL.test(email)) {
      setErroNovo('Isto não parece um endereço de email.');
      return;
    }
    if (emails.includes(email)) {
      setErroNovo('Este email já está na lista.');
      return;
    }
    setErroNovo('');
    setNovo('');
    await gravar([...emails, email], ativo);
  };

  const recolher = async () => {
    setRecolhendo(true);
    try {
      const { data } = await recolherPlataformasAgora();
      const avisos = data.avisos || [];
      toast.success(`Caixa lida: ${data.lidos} relatório(s) encontrado(s).`);
      avisos.forEach((aviso) => toast.warning(aviso, { duration: 8000 }));
      await carregar();
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível ler a caixa.').mensagem);
    } finally {
      setRecolhendo(false);
    }
  };

  const enviar = async () => {
    setEnviando(true);
    try {
      const { data } = await enviarPlataformasAgora();
      toast.success(
        `Email enviado para ${(data.enviado_para || []).length} destinatário(s).`
        + (data.completo === false ? ' (com um relatório em falta)' : ''));
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível enviar.').mensagem);
    } finally {
      setEnviando(false);
    }
  };

  if (loading && !relatorio) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const total = relatorio?.total_da_semana || {};
  const semanais = (relatorio?.plataformas || []).filter((l) => l.ritmo === 'semana');
  const glovo = (relatorio?.plataformas || []).find((l) => l.chave === 'glovo');
  const calendario = relatorio?.glovo || {};
  const problemas = relatorio?.problemas || [];

  return (
    <div className="space-y-6 animate-fade-in" data-testid="painel-plataformas-page">
      <PageHeader icon={Bike} title="Plataformas" subtitle="Painel · Uber Eats, Bolt Food e Glovo">
        <Button type="button" variant="outline" onClick={recolher} disabled={recolhendo}
          data-testid="plataformas-recolher-btn">
          {recolhendo ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            : <RefreshCw className="h-4 w-4 mr-1" />}
          {recolhendo ? 'A ler a caixa...' : 'Ler a caixa agora'}
        </Button>
      </PageHeader>

      <Alert className="border-primary/30 bg-accent/40">
        <Clock className="h-4 w-4" />
        <AlertDescription className="text-sm">
          O email sai <strong>todas as segundas às 08:00</strong>, depois de os relatórios
          das plataformas entrarem de madrugada. A Uber e a Bolt fecham a semana ao domingo
          e pagam na segunda; a <strong>Glovo paga de quinze em quinze dias</strong> — as
          vendas de 1 a 15 no dia 5 do mês seguinte, e as de 16 até ao fim do mês no dia 20.
        </AlertDescription>
      </Alert>

      {/* --- O total da semana ------------------------------------------- */}
      <Card data-testid="plataformas-total">
        <CardContent className="p-5 space-y-3">
          <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
            A receber esta semana (Uber Eats + Bolt Food)
          </p>
          <p className="text-4xl font-heading font-bold leading-none">
            {euros(total.liquido)}
          </p>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>
              {relatorio?.semana
                ? `Semana de ${intervalo(relatorio.semana.inicio, relatorio.semana.fim)}`
                : ''}
            </span>
            {total.pedidos !== null && total.pedidos !== undefined && (
              <span>{total.pedidos} pedidos</span>
            )}
            {total.completo && (
              <Variacao valor={total.variacao} termo="semana anterior"
                houveAnterior={total.anterior !== null && total.anterior !== undefined} />
            )}
          </div>

          {/* **A honestidade do número.** Com uma plataforma em falta, o total
              é de uma só — e tem de se ler que é parcial, senão compara-se com
              a semana passada e conclui-se que as vendas caíram para metade. */}
          {total.completo === false && (
            <div className="flex gap-2 rounded-md bg-amber-50 dark:bg-amber-950/30 p-3">
              <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground">
                <strong className="text-amber-700 dark:text-amber-400">
                  Este total está incompleto.
                </strong>{' '}
                Falta o relatório {(total.em_falta || []).map((n) => `da ${n}`).join(' e ')
                  || 'de uma plataforma'}, por isso o número acima é só do que chegou —
                não o compare com uma semana inteira.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {semanais.map((linha) => <CartaoPlataforma key={linha.chave} linha={linha} />)}
      </div>

      {/* --- A Glovo: calendário + o que estiver lido ---------------------- */}
      <Card data-testid="plataformas-glovo-calendario">
        <CardContent className="p-4 sm:p-5 space-y-4">
          <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold flex items-center gap-2">
            <CalendarClock className="h-4 w-4" />
            Glovo · calendário de pagamentos
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
                Quinzena a decorrer
              </p>
              <p className="font-heading font-bold mt-1">
                {intervalo(calendario.em_curso?.inicio, calendario.em_curso?.fim)}
              </p>
              <p className="text-sm text-muted-foreground mt-0.5">
                {calendario.em_curso?.dias_para_fechar === 0 ? 'fecha hoje'
                  : calendario.em_curso?.dias_para_fechar === 1 ? 'fecha amanhã'
                    : `faltam ${calendario.em_curso?.dias_para_fechar} dias para fechar`}
                {' · paga a '}{diaCurto(calendario.em_curso?.pagamento)}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
                Quinzena fechada
              </p>
              <p className="font-heading font-bold mt-1">
                {intervalo(calendario.fechada?.inicio, calendario.fechada?.fim)}
              </p>
              <p className="text-sm font-semibold text-primary mt-0.5">
                {calendario.fechada?.pago
                  ? `Já devia ter sido paga a ${diaCurto(calendario.fechada?.pagamento)}`
                  : quandoPaga(calendario.fechada)}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {glovo && <CartaoPlataforma linha={glovo} />}

      {/* --- Problemas e cobranças ---------------------------------------- */}
      <Card data-testid="plataformas-problemas">
        <CardContent className="p-4 sm:p-5 space-y-3">
          <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
            Problemas e cobranças
          </p>
          {problemas.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nenhum relatório assinalou problemas, cobranças inesperadas ou penalizações.
            </p>
          ) : (
            <ul className="space-y-2">
              {problemas.map((p, i) => (
                <li key={`${p.plataforma}-${i}`} className="flex gap-2 text-sm">
                  <span className="shrink-0 rounded-full bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 px-2 py-0.5 text-xs font-semibold h-fit">
                    {p.plataforma}
                  </span>
                  <span>{p.texto}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* --- Quem recebe --------------------------------------------------- */}
      <Card>
        <CardContent className="p-4 sm:p-5 space-y-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="font-medium">Envio automático</p>
              <p className="text-sm text-muted-foreground">
                {ativo ? 'Ligado — sai todas as segundas às 08:00.'
                  : 'Desligado — não sai nenhum email.'}
              </p>
            </div>
            <Switch
              checked={ativo} disabled={saving}
              onCheckedChange={(v) => gravar(emails, v)}
              data-testid="plataformas-ativo-switch"
            />
          </div>

          <div className="border-t pt-4">
            <Label>Quem recebe</Label>
            <p className="text-sm text-muted-foreground mt-1 mb-3">
              Toda a gente nesta lista recebe o email completo, com as três plataformas.
            </p>
            <div className="flex flex-wrap gap-2 items-start">
              <div className="flex-1 min-w-[240px]">
                <Input
                  value={novo}
                  onChange={(e) => { setNovo(e.target.value); setErroNovo(''); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); juntar(); } }}
                  placeholder="nome@empresa.pt"
                  disabled={saving}
                  data-testid="plataformas-novo-email"
                />
                {erroNovo && <p className="text-sm text-destructive mt-1">{erroNovo}</p>}
              </div>
              <Button type="button" onClick={juntar} disabled={saving || !novo.trim()}
                data-testid="plataformas-juntar-btn">
                <Plus className="h-4 w-4 mr-1" />Juntar
              </Button>
            </div>

            {emails.length === 0 ? (
              <div className="rounded-md border border-dashed p-6 text-center mt-3"
                data-testid="plataformas-lista-vazia">
                <Mail className="h-8 w-8 text-muted-foreground/50 mx-auto mb-2" strokeWidth={1.5} />
                <p className="text-sm text-muted-foreground">
                  Ninguém na lista — o email de segunda não é enviado a ninguém.
                </p>
              </div>
            ) : (
              <div className="divide-y rounded-md border mt-3" data-testid="plataformas-lista">
                {emails.map((email) => (
                  <div key={email} className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <span className="text-sm break-all">{email}</span>
                    <Button type="button" variant="ghost" size="icon"
                      onClick={() => gravar(emails.filter((e) => e !== email), ativo)}
                      disabled={saving} aria-label={`Tirar ${email} da lista`}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="border-t pt-4 flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="font-medium">Enviar agora</p>
              <p className="text-sm text-muted-foreground">
                Manda o email com o que já está lido, para veres como fica sem esperar
                pela segunda. <strong>Não gasta o envio automático</strong> — o das 08:00
                sai na mesma.
              </p>
            </div>
            <Button type="button" variant="outline" onClick={enviar}
              disabled={enviando || emails.length === 0}
              data-testid="plataformas-enviar-agora-btn">
              {enviando ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                : <Send className="h-4 w-4 mr-1" />}
              {enviando ? 'A enviar...' : 'Enviar agora'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* --- Histórico ----------------------------------------------------- */}
      <Card>
        <CardContent className="p-4 sm:p-5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold mb-3">
            Relatórios já lidos
          </p>
          {historico.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="plataformas-historico-vazio">
              Ainda não foi lido nenhum relatório. Carrega em «Ler a caixa agora» para
              procurar os que já estão na caixa de email.
            </p>
          ) : (
            <div className="overflow-x-auto" data-testid="plataformas-historico">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Período</TableHead>
                    <TableHead>Plataforma</TableHead>
                    <TableHead>Loja</TableHead>
                    <TableHead className="text-right">A receber</TableHead>
                    <TableHead className="text-right">Pedidos</TableHead>
                    <TableHead>Lido de</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {historico.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="whitespace-nowrap">
                        {intervalo(r.periodo_inicio, r.periodo_fim)}
                      </TableCell>
                      <TableCell>{NOMES[r.plataforma] || r.plataforma}</TableCell>
                      <TableCell className="max-w-[180px] truncate">
                        {r.loja || <span className="text-muted-foreground">não identificada</span>}
                      </TableCell>
                      <TableCell className="text-right font-semibold whitespace-nowrap">
                        {euros(r.valores?.liquido)}
                      </TableCell>
                      <TableCell className="text-right">
                        {r.valores?.pedidos ?? '—'}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground max-w-[280px] truncate">
                        {r.origem?.assunto || '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
