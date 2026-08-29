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
// Os MESMOS gráficos do painel — o dono pediu-os aqui, e uma segunda cópia
// divergia à primeira correcção.
import { GraficoDeArea, GraficoDeBarras } from './GraficosDaFaturacao';
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

// As três vistas que NÃO são uma linha do tempo contínua. Entre «Segunda» e
// «Terça» não há nada, e uma curva a ligá-las desenha uma subida que não
// existe — por isso estas são barras e as outras são área.
const DE_BARRAS = ['hora', 'dia_semana', 'mes'];

// O rótulo do eixo. A série vem com o rótulo já feito pelo servidor — «01-08»
// para os dias, «14h», «Segunda-feira», «Agosto» —, mas um dia inteiro
// escrito por extenso não cabe num eixo com trinta datas: corta-se ao dia e
// ao mês, que é o que o painel também mostra.
const rotuloDoEixo = (bruto) => {
  const texto = String(bruto == null ? '' : bruto);
  // 'AAAA-MM-DD' -> 'dd-mm' (parte a string; sem Date, para nunca tropeçar
  // em fusos).
  if (/^\d{4}-\d{2}-\d{2}$/.test(texto)) {
    const [, m, d] = texto.split('-');
    return `${d}-${m}`;
  }
  return texto;
};

export default function FatRelatorios() {
  const [vista, setVista] = useState('produto');
  const [filtros, setFiltros] = useState({
    de: primeiroDoMes(), ate: hoje(), loja_id: 'todas', utilizador_id: 'todos',
    categoria_id: 'todas',
  });
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(false);

  // Os pontos do gráfico. O servidor manda `serie` já pronta — por dia nas
  // vistas de área, e as PRÓPRIAS linhas da tabela nas de barras (é a mesma
  // pergunta desenhada de duas maneiras, e por isso nunca podem discordar).
  const pontosDoGrafico = useMemo(
    () => (dados?.serie || []).map((p) => ({
      rotulo: rotuloDoEixo(p.rotulo), v: Number(p.valor) || 0,
    })),
    [dados]);
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
            <CardContent className="p-4 sm:p-5 space-y-3">
              <p className="text-sm font-semibold">
                {DE_BARRAS.includes(vista)
                  ? (VISTAS.find((v) => v.id === vista) || {}).nome
                  : 'Faturação diária'}
                <span className="font-normal text-muted-foreground">
                  {' · '}{filtros.de} a {filtros.ate}
                </span>
              </p>
              {DE_BARRAS.includes(vista) ? (
                <GraficoDeBarras pontos={pontosDoGrafico} testid="fat-relatorio-barras"
                  ariaLabel="Vendas do período" />
              ) : (
                <GraficoDeArea pontos={pontosDoGrafico} testid="fat-relatorio-area"
                  ariaLabel="Faturação diária do período" />
              )}
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
                    ) : dados.linhas.map((l, i) => (
                      <TableRow key={String(l.chave)}>
                        <TableCell className="font-medium">
                          {l.rotulo}
                          {/* **Os tamanhos, por baixo do artigo.** No catálogo
                              há UM açaí e o tamanho é uma personalização dele:
                              «Açaí 25» é verdade e não responde a nada. Só a
                              vista de Produtos os traz — um tamanho reparte um
                              artigo, não uma loja. */}
                          {(l.tamanhos || []).length > 0 ? (
                            <span className="block mt-0.5 text-xs font-normal text-muted-foreground tabular-nums"
                              data-testid={`fat-relatorio-tamanhos-${i}`}>
                              {l.tamanhos.map((t) => `${t.nome} ${t.quantidade}`).join(' · ')}
                            </span>
                          ) : null}
                        </TableCell>
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
