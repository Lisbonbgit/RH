import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getRelatorio, getLojas, getUtilizadores, getCategorias, detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { BarChart3, Search, Loader2, Download, AlertTriangle } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// **Os nove relatórios são a mesma tabela.** Muda a primeira coluna e mudam os
// filtros — por isso são um ecrã só com um selector de vista, e não nove
// ecrãs. Nove cópias da mesma tabela acabam a divergir na primeira correcção
// que só se fizer numa delas.
//
// As colunas são as dos prints do Vendus, e o rodapé é o de lá, à letra:
// "Nº Vendas" conta faturas, "Nº Rectificações" conta notas de crédito, e as
// duas não se somam.

const VISTAS = [
  { id: 'produto', nome: 'Produtos', coluna: 'Produto', filtros: ['loja', 'utilizador', 'categoria'] },
  { id: 'cliente', nome: 'Clientes', coluna: 'Cliente', filtros: ['loja', 'utilizador', 'categoria'] },
  { id: 'categoria', nome: 'Categorias', coluna: 'Categoria', filtros: ['loja', 'utilizador'] },
  { id: 'loja', nome: 'Lojas', coluna: 'Loja', filtros: ['utilizador', 'categoria'] },
  { id: 'utilizador', nome: 'Utilizadores', coluna: 'Utilizador', filtros: ['loja', 'categoria'] },
  { id: 'dia', nome: 'Diário', coluna: 'Dia', filtros: ['loja', 'utilizador', 'categoria'] },
  { id: 'hora', nome: 'Por Hora', coluna: 'Hora', filtros: ['loja'] },
  { id: 'dia_semana', nome: 'Dias da Semana', coluna: 'Dia da semana', filtros: ['loja'] },
  { id: 'mes', nome: 'Mensal', coluna: 'Mês', filtros: ['loja'] },
];

const euros = (valor) => (valor === null || valor === undefined
  ? '—'
  : `€ ${Number(valor).toLocaleString('pt-PT', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`);

const hoje = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Lisbon' });
const primeiroDoMes = () => hoje().slice(0, 8) + '01';

// O gráfico é SVG à mão, como o do Dashboard — sem biblioteca nova para
// desenhar barras e uma linha.
function Grafico({ serie, barras }) {
  if (!serie || serie.length === 0) return null;
  const valores = serie.map((p) => Number(p.valor) || 0);
  const maximo = Math.max(...valores, 0);
  const minimo = Math.min(...valores, 0);
  const amplitude = (maximo - minimo) || 1;
  const largura = 720;
  const altura = 200;
  const passo = serie.length > 1 ? largura / (serie.length - 1) : largura;
  const y = (v) => altura - ((v - minimo) / amplitude) * (altura - 20) - 10;

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${largura} ${altura + 26}`} className="w-full min-w-[560px]"
        xmlns="http://www.w3.org/2000/svg" role="img"
        aria-label="Evolução das vendas no período">
        <line x1="0" y1={y(0)} x2={largura} y2={y(0)} stroke="currentColor"
          className="text-border" strokeWidth="1" />
        {barras ? serie.map((p, i) => {
          const largo = Math.max(4, (largura / serie.length) * 0.6);
          const x = serie.length > 1 ? i * (largura / serie.length) + (largura / serie.length - largo) / 2 : 0;
          const topo = y(Math.max(0, Number(p.valor) || 0));
          return (
            <rect key={i} x={x} y={topo} width={largo} height={Math.abs(y(0) - topo)}
              className="fill-primary/70" />
          );
        }) : (
          <polyline
            fill="none" strokeWidth="2" className="stroke-primary"
            points={serie.map((p, i) => `${i * passo},${y(Number(p.valor) || 0)}`).join(' ')}
          />
        )}
        {serie.map((p, i) => (
          (serie.length <= 12 || i % Math.ceil(serie.length / 12) === 0) ? (
            <text key={`r${i}`} x={barras ? i * (largura / serie.length) + (largura / serie.length) / 2 : i * passo}
              y={altura + 18} textAnchor="middle" className="fill-muted-foreground"
              style={{ fontSize: 11 }}>
              {String(p.rotulo).length > 7 ? String(p.rotulo).slice(5) : p.rotulo}
            </text>
          ) : null
        ))}
      </svg>
    </div>
  );
}

export default function FatRelatorios() {
  const [vista, setVista] = useState('produto');
  const [filtros, setFiltros] = useState({
    de: primeiroDoMes(), ate: hoje(), loja_id: 'todas', utilizador_id: 'todos',
    categoria_id: 'todas',
  });
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(false);
  const [lojas, setLojas] = useState([]);
  const [utilizadores, setUtilizadores] = useState([]);
  const [categorias, setCategorias] = useState([]);

  const actual = useMemo(() => VISTAS.find((v) => v.id === vista) || VISTAS[0], [vista]);

  useEffect(() => {
    getLojas().then(({ data }) => setLojas(data || [])).catch(() => {});
    getUtilizadores().then(({ data }) => setUtilizadores(data || [])).catch(() => {});
    getCategorias().then(({ data }) => setCategorias(data || [])).catch(() => {});
  }, []);

  const procurar = useCallback(async (qualVista) => {
    setCarregando(true);
    try {
      const { data } = await getRelatorio(qualVista, {
        de: filtros.de,
        ate: filtros.ate,
        // "todas"/"todos" é a AUSÊNCIA de filtro e não viaja — mandá-los como
        // texto punha o servidor a procurar uma loja com o id "todas".
        loja_id: filtros.loja_id === 'todas' ? undefined : filtros.loja_id,
        utilizador_id: filtros.utilizador_id === 'todos' ? undefined : filtros.utilizador_id,
        categoria_id: filtros.categoria_id === 'todas' ? undefined : filtros.categoria_id,
      });
      setDados(data);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível carregar o relatório.').mensagem);
    } finally {
      setCarregando(false);
    }
  }, [filtros]);

  useEffect(() => { procurar(vista); /* eslint-disable-next-line */ }, [vista]);

  const exportarCsv = () => {
    if (!dados) return;
    const cabecalho = [
      actual.coluna, 'Vendas c/IVA', 'Vendas', 'Custos', 'Resultado',
      ...(dados.com_quantidade ? ['Quantidade'] : []),
      'Nº Vendas', 'Nº Rectificações',
    ];
    const linha = (l) => [
      l.rotulo, l.bruto, l.liquido,
      l.custo === null ? '' : l.custo,
      l.resultado === null ? '' : l.resultado,
      ...(dados.com_quantidade ? [l.quantidade] : []),
      l.faturas, l.rectificacoes,
    ];
    const csv = [cabecalho, ...dados.linhas.map(linha), linha(dados.total)]
      .map((cols) => cols.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(';'))
      .join('\n');
    const url = window.URL.createObjectURL(new Blob(["﻿" + csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `relatorio-${vista}-${filtros.de}-a-${filtros.ate}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const mostra = (filtro) => actual.filtros.includes(filtro);
  const temQuantidade = dados?.com_quantidade;

  return (
    <div className="space-y-6">
      <PageHeader icon={BarChart3} title="Relatórios" subtitle="Vendas por produto, cliente, loja, utilizador e período" />

      <div className="flex gap-2 overflow-x-auto pb-1">
        {VISTAS.map((v) => (
          <button
            key={v.id} type="button" onClick={() => setVista(v.id)}
            aria-pressed={vista === v.id}
            data-testid={`vista-${v.id}`}
            className={`h-10 px-4 rounded-lg border text-sm font-medium whitespace-nowrap shrink-0 transition-colors ${
              vista === v.id ? 'bg-primary text-primary-foreground border-primary' : 'bg-card hover:bg-accent'
            }`}
          >
            {v.nome}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="p-4 grid gap-3 md:grid-cols-6 items-end">
          <div className="space-y-1">
            <Label htmlFor="rel-de">De</Label>
            <Input id="rel-de" type="date" value={filtros.de}
              onChange={(e) => setFiltros({ ...filtros, de: e.target.value })}
              data-testid="relatorios-de" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="rel-ate">Até</Label>
            <Input id="rel-ate" type="date" value={filtros.ate}
              onChange={(e) => setFiltros({ ...filtros, ate: e.target.value })}
              data-testid="relatorios-ate" />
          </div>
          {mostra('loja') && (
            <div className="space-y-1">
              <Label>Loja</Label>
              <Select value={filtros.loja_id} onValueChange={(v) => setFiltros({ ...filtros, loja_id: v })}>
                <SelectTrigger data-testid="relatorios-loja"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="todas">Todas as lojas</SelectItem>
                  {lojas.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
          {mostra('utilizador') && (
            <div className="space-y-1">
              <Label>Utilizador</Label>
              <Select value={filtros.utilizador_id} onValueChange={(v) => setFiltros({ ...filtros, utilizador_id: v })}>
                <SelectTrigger data-testid="relatorios-utilizador"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="todos">Todos os utilizadores</SelectItem>
                  {utilizadores.map((u) => <SelectItem key={u.id} value={u.id}>{u.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
          {mostra('categoria') && (
            <div className="space-y-1">
              <Label>Categoria</Label>
              <Select value={filtros.categoria_id} onValueChange={(v) => setFiltros({ ...filtros, categoria_id: v })}>
                <SelectTrigger data-testid="relatorios-categoria"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="todas">Todas as categorias</SelectItem>
                  {categorias.map((c) => <SelectItem key={c.id} value={c.id}>{c.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
          <Button onClick={() => procurar(vista)} disabled={carregando} data-testid="relatorios-aplicar">
            {carregando ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
            Aplicar
          </Button>
        </CardContent>
      </Card>

      {dados && (
        <>
          {dados.total.custo_incompleto && (
            <p className="text-sm text-warning flex items-start gap-1.5">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              Há artigos sem preço de custo — por isso as colunas Custos e Resultado aparecem a
              "—" nas linhas afectadas. Preencha o custo em Catálogo → Produtos e elas acendem-se.
            </p>
          )}

          <Card>
            <CardContent className="p-4">
              <Grafico serie={dados.serie} barras={['hora', 'dia_semana', 'mes'].includes(vista)} />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <div className="flex items-center justify-between p-4">
                <p className="font-medium">Vendas</p>
                <Button variant="outline" onClick={exportarCsv} data-testid="relatorios-csv">
                  <Download className="h-4 w-4 mr-2" /> Exportar CSV
                </Button>
              </div>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{actual.coluna}</TableHead>
                      <TableHead className="text-right">Vendas c/IVA</TableHead>
                      <TableHead className="text-right">Vendas</TableHead>
                      <TableHead className="text-right">Custos</TableHead>
                      <TableHead className="text-right">Resultado</TableHead>
                      {temQuantidade && <TableHead className="text-right">Quantidade</TableHead>}
                      <TableHead className="text-right">Nº Vendas</TableHead>
                      <TableHead className="text-right">Nº Rectificações</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {dados.linhas.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={temQuantidade ? 8 : 7} className="text-center text-muted-foreground py-8">
                          Sem vendas neste período.
                        </TableCell>
                      </TableRow>
                    ) : dados.linhas.map((l) => (
                      <TableRow key={String(l.chave)}>
                        <TableCell className="font-medium">{l.rotulo}</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(l.bruto)}</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(l.liquido)}</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(l.custo)}</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(l.resultado)}</TableCell>
                        {temQuantidade && (
                          <TableCell className="text-right tabular-nums">{l.quantidade}</TableCell>
                        )}
                        <TableCell className="text-right tabular-nums">{l.faturas}</TableCell>
                        <TableCell className="text-right tabular-nums">{l.rectificacoes}</TableCell>
                      </TableRow>
                    ))}
                    {dados.linhas.length > 0 && (
                      <TableRow className="bg-muted/50 font-medium">
                        <TableCell>TOTAL</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(dados.total.bruto)}</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(dados.total.liquido)}</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(dados.total.custo)}</TableCell>
                        <TableCell className="text-right tabular-nums">{euros(dados.total.resultado)}</TableCell>
                        {temQuantidade && (
                          <TableCell className="text-right tabular-nums">{dados.total.quantidade}</TableCell>
                        )}
                        <TableCell className="text-right tabular-nums">{dados.total.faturas}</TableCell>
                        <TableCell className="text-right tabular-nums">{dados.total.rectificacoes}</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
              <div className="p-4 text-xs text-muted-foreground space-y-0.5">
                <p>Nº Vendas: total de documentos do tipo Fatura Simplificada.</p>
                <p>Nº Rectificações: total de documentos do tipo Nota de Crédito — o valor delas
                  está subtraído nas colunas de dinheiro.</p>
              </div>
            </CardContent>
          </Card>

          {dados.truncado && (
            <p className="text-sm text-warning flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4" />
              Período grande de mais para somar de uma vez — reduza o intervalo.
            </p>
          )}
        </>
      )}
    </div>
  );
}
