import React, { useCallback, useEffect, useState } from 'react';
import { getHistoricoDeCaixa, getTurno, getLojas } from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Badge } from '../../../components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import {
  Banknote, ChevronDown, ChevronRight, Loader2, ArrowLeft,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const fmtEUR = (n) => (n === null || n === undefined
  ? '—'
  : new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(Number(n) || 0));

const DIAS = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira',
  'Quinta-feira', 'Sexta-feira', 'Sábado'];
const MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];

// `2026-08-26` -> `Quarta-feira` / `26 de Agosto de 2026`. Construído a partir
// dos pedaços da string e não de `new Date(texto)`: o construtor lê "AAAA-MM-DD"
// como UTC e, em Lisboa no Verão, mostrava o dia anterior a partir das 23h.
const dataPorExtenso = (dia) => {
  const [ano, mes, d] = String(dia || '').split('-').map(Number);
  if (!ano || !mes || !d) return { semana: '', completa: dia || '' };
  return {
    semana: DIAS[new Date(Date.UTC(ano, mes - 1, d)).getUTCDay()] || '',
    completa: `${d} de ${MESES[mes - 1]} de ${ano}`,
  };
};

const hoje = () => new Date().toISOString().slice(0, 10);
const haUmMes = () => {
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 10);
};

// A pastilha da gaveta: certa, falta, sobra, ou o turno ainda aberto. A cor
// nunca vai sozinha — leva sempre a palavra, porque quem não distingue verde
// de vermelho tem de ler a mesma coisa.
function PastilhaDaGaveta({ fecho }) {
  if (fecho.estado === 'aberto') {
    return <Badge variant="outline" className="bg-amber-50 text-amber-800 border-amber-300">Turno ainda aberto</Badge>;
  }
  const d = fecho.diferenca;
  if (d === null || d === undefined) return null;
  if (Math.abs(d) < 0.005) {
    return <Badge variant="outline" className="bg-success/10 text-success border-success/30">Gaveta certa</Badge>;
  }
  return (
    <Badge variant="outline" className={d < 0
      ? 'bg-destructive/10 text-destructive border-destructive/30'
      : 'bg-success/10 text-success border-success/30'}>
      {d < 0 ? `Falta ${fmtEUR(Math.abs(d))}` : `Sobra ${fmtEUR(d)}`}
    </Badge>
  );
}

function Seccao({ titulo, valor, children, testid }) {
  const [aberta, setAberta] = useState(false);
  return (
    <div className="border-t first:border-t-0" data-testid={testid}>
      <button
        type="button"
        onClick={() => setAberta((a) => !a)}
        className="w-full flex items-center gap-2 px-4 py-3.5 text-left hover:bg-muted/40"
      >
        {aberta ? <ChevronDown className="h-4 w-4 shrink-0" />
          : <ChevronRight className="h-4 w-4 shrink-0" />}
        <span className="font-medium flex-1">{titulo}</span>
        {valor !== undefined && (
          <span className="font-semibold tabular-nums shrink-0">{valor}</span>
        )}
      </button>
      {aberta && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

function Tabela({ colunas, linhas, vazio }) {
  if (!linhas.length) {
    return <p className="text-sm text-muted-foreground py-2">{vazio}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted-foreground">
            {colunas.map((c, i) => (
              <th key={c.titulo} className={`font-medium pb-2 ${i ? 'text-right' : 'text-left'}`}>
                {c.titulo}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {linhas.map((linha, i) => (
            <tr key={i} className="border-t">
              {colunas.map((c, j) => (
                <td key={c.titulo} className={`py-2 ${j ? 'text-right tabular-nums' : ''}`}>
                  {c.ler(linha)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Detalhe({ id, onVoltar }) {
  const [turno, setTurno] = useState(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    let vivo = true;
    getTurno(id)
      .then(({ data }) => { if (vivo) setTurno(data); })
      .catch(() => { if (vivo) setErro(true); });
    return () => { vivo = false; };
  }, [id]);

  if (erro) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" onClick={onVoltar}><ArrowLeft className="h-4 w-4 mr-1" />Voltar</Button>
        <p className="text-sm text-muted-foreground">Não foi possível carregar este turno.</p>
      </div>
    );
  }
  if (!turno) {
    return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
  }

  const data = dataPorExtenso(turno.dia);
  return (
    <div className="space-y-4 animate-fade-in" data-testid="turno-detalhe">
      <Button variant="ghost" onClick={onVoltar} data-testid="voltar-ao-historico">
        <ArrowLeft className="h-4 w-4 mr-1" />Movimentos de Caixa
      </Button>

      <div>
        <h2 className="font-heading font-bold text-xl">{turno.loja_nome}</h2>
        <p className="text-sm text-muted-foreground">
          {turno.caixa_nome} · {data.semana}, {data.completa}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardContent className="p-4 sm:p-5">
            <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">Abertura</p>
            <p className="font-heading font-bold text-2xl mt-1 tabular-nums">{fmtEUR(turno.abertura.valor)}</p>
            <p className="text-sm text-muted-foreground mt-2">
              {turno.abertura.hora || '—'} · {turno.abertura.por || '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 sm:p-5">
            <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">Fecho</p>
            <div className="flex items-baseline gap-4 mt-1">
              <div>
                <p className="text-xs text-muted-foreground">Esperado</p>
                <p className="font-heading font-bold text-2xl tabular-nums">{fmtEUR(turno.fecho.esperado)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Contado</p>
                <p className="font-heading font-bold text-2xl tabular-nums">{fmtEUR(turno.fecho.contado)}</p>
              </div>
            </div>
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <PastilhaDaGaveta fecho={turno.fecho} />
              <span className="text-sm text-muted-foreground">
                {turno.fecho.hora ? `${turno.fecho.hora} · ${turno.fecho.por || '—'}` : ''}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <Seccao titulo="Resumo dos movimentos" valor={fmtEUR(turno.entradas - turno.saidas)} testid="sec-resumo">
            <Tabela
              colunas={[
                { titulo: '', ler: (l) => l.nome },
                { titulo: 'Valor', ler: (l) => fmtEUR(l.valor) },
              ]}
              linhas={[
                { nome: 'Fundo de maneio', valor: turno.abertura.valor },
                { nome: 'Vendas em dinheiro', valor: turno.vendas_dinheiro },
                { nome: 'Entradas', valor: turno.entradas },
                { nome: 'Saídas', valor: -turno.saidas },
                { nome: 'Esperado na gaveta', valor: turno.esperado },
              ]}
              vazio=""
            />
          </Seccao>

          <Seccao titulo="Lista dos movimentos" valor={turno.movimentos.length || '0'} testid="sec-movimentos">
            <Tabela
              colunas={[
                { titulo: 'Hora', ler: (m) => m.hora || '—' },
                { titulo: 'Motivo', ler: (m) => m.motivo || (m.tipo === 'entrada' ? 'Entrada' : 'Saída') },
                { titulo: 'Quem', ler: (m) => m.por || '—' },
                { titulo: 'Valor', ler: (m) => (m.tipo === 'saida' ? `− ${fmtEUR(m.valor)}` : fmtEUR(m.valor)) },
              ]}
              linhas={turno.movimentos}
              vazio="Nenhuma entrada nem saída de dinheiro neste turno."
            />
          </Seccao>

          <Seccao titulo="Tipos de pagamento" valor={fmtEUR(turno.total_faturado)} testid="sec-pagamentos">
            <Tabela
              colunas={[
                { titulo: '', ler: (p) => p.nome || '—' },
                { titulo: 'Quantos', ler: (p) => p.quantos },
                { titulo: 'Total', ler: (p) => fmtEUR(p.total) },
              ]}
              linhas={turno.pagamentos}
              vazio="Sem pagamentos registados neste turno."
            />
            {turno.pagamentos_por_registar > 0 && (
              <p className="text-sm text-destructive mt-3">
                {fmtEUR(turno.pagamentos_por_registar)} facturados sem pagamento por baixo.
              </p>
            )}
          </Seccao>

          <Seccao titulo="Produtos vendidos" testid="sec-artigos">
            <Tabela
              colunas={[
                { titulo: '', ler: (a) => (
                  <span>
                    {a.nome}
                    {a.variantes.length > 0 && (
                      <span className="text-muted-foreground text-xs ml-2">
                        {a.variantes.map((v) => `${v.nome} ${v.quantidade}`).join(' · ')}
                      </span>
                    )}
                  </span>
                ) },
                { titulo: 'Unidades', ler: (a) => a.quantidade },
              ]}
              linhas={turno.artigos}
              vazio="Sem artigos vendidos neste turno."
            />
          </Seccao>

          <Seccao titulo="Mapa de impostos" valor={fmtEUR(turno.iva_total)} testid="sec-imposto">
            <Tabela
              colunas={[
                { titulo: 'Taxa', ler: (l) => l.tax_id || l.nome || '—' },
                { titulo: 'Base', ler: (l) => fmtEUR(l.base) },
                { titulo: 'IVA', ler: (l) => fmtEUR(l.iva) },
                { titulo: 'Total', ler: (l) => fmtEUR(l.total) },
              ]}
              linhas={turno.mapa_imposto}
              vazio="Sem documentos emitidos neste turno."
            />
          </Seccao>

          <Seccao titulo="Documentos emitidos" valor={turno.quantos_documentos} testid="sec-documentos">
            <p className="text-sm text-muted-foreground">
              {turno.quantos_documentos === 1
                ? '1 documento emitido, no total de '
                : `${turno.quantos_documentos} documentos emitidos, no total de `}
              <strong className="text-foreground">{fmtEUR(turno.total_faturado)}</strong>
              {' '}(base {fmtEUR(turno.base_tributavel)} + IVA {fmtEUR(turno.iva_total)}).
            </p>
          </Seccao>
        </CardContent>
      </Card>
    </div>
  );
}

export default function FatMovimentosCaixa() {
  const [lojas, setLojas] = useState([]);
  const [lojaId, setLojaId] = useState('');
  const [de, setDe] = useState(haUmMes());
  const [ate, setAte] = useState(hoje());
  const [turnos, setTurnos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [aberto, setAberto] = useState(null);

  useEffect(() => {
    getLojas().then(({ data }) => setLojas(data || [])).catch(() => {});
  }, []);

  const procurar = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getHistoricoDeCaixa({
        loja_id: lojaId || undefined, de, ate,
      });
      setTurnos(data || []);
    } catch (error) {
      toast.error('Erro ao carregar os movimentos de caixa');
    } finally {
      setLoading(false);
    }
  }, [lojaId, de, ate]);

  useEffect(() => { procurar(); }, [procurar]);

  if (aberto) {
    return <Detalhe id={aberto} onVoltar={() => setAberto(null)} />;
  }

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-movimentos-caixa-page">
      <PageHeader icon={Banknote} title="Movimentos de Caixa" subtitle="Faturação · POS" />

      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[200px]">
          <Select value={lojaId || '__todas__'} onValueChange={(v) => setLojaId(v === '__todas__' ? '' : v)}>
            <SelectTrigger data-testid="filtro-loja"><SelectValue placeholder="Todas as lojas" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__todas__">Todas as lojas</SelectItem>
              {lojas.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <Input type="date" value={de} onChange={(e) => setDe(e.target.value)}
          className="w-40" data-testid="filtro-de" />
        <span className="text-sm text-muted-foreground pb-2">até</span>
        <Input type="date" value={ate} onChange={(e) => setAte(e.target.value)}
          className="w-40" data-testid="filtro-ate" />
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : turnos.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center py-12 text-center">
            <Banknote className="h-10 w-10 text-muted-foreground/50 mb-3" strokeWidth={1.5} />
            <p className="font-medium">Nenhum turno neste período</p>
            <p className="text-sm text-muted-foreground mt-1">
              Aparecem aqui assim que uma loja abrir a caixa no POS.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3" data-testid="lista-de-turnos">
          {turnos.map((t) => {
            const data = dataPorExtenso(t.dia);
            return (
              <Card key={t.id} data-testid={`turno-${t.id}`}>
                <CardContent className="p-4 sm:p-5">
                  <div className="flex flex-wrap items-start gap-4">
                    <div className="min-w-[160px]">
                      <p className="font-heading font-semibold">{data.semana}</p>
                      <p className="text-sm text-muted-foreground">{data.completa}</p>
                      <p className="font-heading font-bold text-xl mt-2 tabular-nums text-primary">
                        {fmtEUR(t.faturacao)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t.loja_nome} · {t.documentos} doc.
                      </p>
                    </div>

                    <div className="flex-1 min-w-[240px] grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                      <span className="text-muted-foreground">Abertura</span>
                      <span className="text-right tabular-nums">
                        {t.abertura.hora || '—'} · {fmtEUR(t.abertura.valor)}
                      </span>
                      <span className="text-muted-foreground">Esperado</span>
                      <span className="text-right tabular-nums">{fmtEUR(t.fecho.esperado)}</span>
                      <span className="text-muted-foreground">Contado</span>
                      <span className="text-right tabular-nums">{fmtEUR(t.fecho.contado)}</span>
                      <span className="col-span-2 text-xs text-muted-foreground">
                        {t.fecho.por ? `Fechado por ${t.fecho.por}` : ''}
                      </span>
                    </div>

                    <div className="flex flex-col items-end gap-2">
                      <PastilhaDaGaveta fecho={t.fecho} />
                      <Button variant="outline" size="sm" onClick={() => setAberto(t.id)}
                        data-testid={`detalhe-${t.id}`}>
                        Detalhe
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
