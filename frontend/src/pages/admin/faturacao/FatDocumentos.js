import React, { useCallback, useEffect, useState } from 'react';
import {
  getDocumentos, getDocumento, getLojas, detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { FileText, Search, Loader2, ChevronLeft, ChevronRight, AlertTriangle } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// **As faturas já emitidas, de todas as lojas.** É leitura e mais nada: daqui
// não se emite, não se anula e não se reimprime. A pergunta a que este ecrã
// responde é a do gestor — «o que se emitiu, em que loja, naquele intervalo?».
//
// A do balcão é outra («onde está a fatura daquele cliente?») e vive no POS,
// com o âmbito da loja do token. São duas rotas diferentes de propósito; o que
// as duas partilham é o MONTADOR da fatura, no servidor.

const euros = (valor) => `€ ${(Number(valor) || 0).toLocaleString('pt-PT', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})}`;

// "dd/mm/aaaa às hh:mm", na hora de LISBOA — o `emitido_em` está em UTC, e um
// ecrã que o mostrasse em cru punha a venda das 00h30 no dia anterior.
const formatarData = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('pt-PT', {
    timeZone: 'Europe/Lisbon', day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).replace(', ', ' às ');
};

const hoje = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Lisbon' });
const primeiroDoMes = () => hoje().slice(0, 8) + '01';

export default function FatDocumentos() {
  const [filtros, setFiltros] = useState({
    de: primeiroDoMes(), ate: hoje(), loja_id: 'todas', tipo: 'todos', q: '',
  });
  const [pagina, setPagina] = useState(1);
  const [dados, setDados] = useState({ documentos: [], total: 0, por_pagina: 50, resumo: null });
  const [lojas, setLojas] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [aberto, setAberto] = useState(null);
  const [aAbrir, setAAbrir] = useState(false);

  useEffect(() => {
    getLojas().then(({ data }) => setLojas(data || [])).catch(() => {});
  }, []);

  const procurar = useCallback(async (pag) => {
    setCarregando(true);
    try {
      // Os valores "todas"/"todos" NÃO viajam: são a ausência de filtro, e
      // mandá-los como texto fazia o servidor procurar uma loja com esse id.
      const { data } = await getDocumentos({
        de: filtros.de || undefined,
        ate: filtros.ate || undefined,
        loja_id: filtros.loja_id === 'todas' ? undefined : filtros.loja_id,
        tipo: filtros.tipo === 'todos' ? undefined : filtros.tipo,
        q: filtros.q.trim() || undefined,
        pagina: pag,
      });
      setDados(data);
      setPagina(pag);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível carregar os documentos.').mensagem);
    } finally {
      setCarregando(false);
    }
  }, [filtros]);

  useEffect(() => { procurar(1); /* eslint-disable-next-line */ }, []);

  const abrir = async (documento) => {
    setAAbrir(true);
    try {
      const { data } = await getDocumento(documento.id);
      setAberto(data);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível abrir a fatura.').mensagem);
    } finally {
      setAAbrir(false);
    }
  };

  const nomeDaLoja = (id) => lojas.find((l) => l.id === id)?.nome || '—';
  const paginas = Math.max(1, Math.ceil((dados.total || 0) / (dados.por_pagina || 50)));

  return (
    <div className="space-y-6">
      <PageHeader icon={FileText} title="Documentos" subtitle="Faturas e notas de crédito emitidas" />

      <Card>
        <CardContent className="p-4 grid gap-3 md:grid-cols-6 items-end">
          <div className="space-y-1">
            <Label htmlFor="doc-de">De</Label>
            <Input id="doc-de" type="date" value={filtros.de}
              onChange={(e) => setFiltros({ ...filtros, de: e.target.value })}
              data-testid="documentos-de" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="doc-ate">Até</Label>
            <Input id="doc-ate" type="date" value={filtros.ate}
              onChange={(e) => setFiltros({ ...filtros, ate: e.target.value })}
              data-testid="documentos-ate" />
          </div>
          <div className="space-y-1">
            <Label>Loja</Label>
            <Select value={filtros.loja_id}
              onValueChange={(v) => setFiltros({ ...filtros, loja_id: v })}>
              <SelectTrigger data-testid="documentos-loja"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todas">Todas as lojas</SelectItem>
                {lojas.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Tipo</Label>
            <Select value={filtros.tipo}
              onValueChange={(v) => setFiltros({ ...filtros, tipo: v })}>
              <SelectTrigger data-testid="documentos-tipo"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todos</SelectItem>
                <SelectItem value="FS">Faturas</SelectItem>
                <SelectItem value="NC">Notas de crédito</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="doc-q">Número ou NIF</Label>
            <Input id="doc-q" value={filtros.q} placeholder="01P2026/17 ou 517542510"
              onChange={(e) => setFiltros({ ...filtros, q: e.target.value })}
              onKeyDown={(e) => { if (e.key === 'Enter') procurar(1); }}
              data-testid="documentos-q" />
          </div>
          <Button onClick={() => procurar(1)} disabled={carregando} data-testid="documentos-procurar">
            {carregando ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
            Procurar
          </Button>
        </CardContent>
      </Card>

      {dados.resumo && (
        <Card>
          <CardContent className="p-4 flex flex-wrap items-baseline gap-x-8 gap-y-2">
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Faturado</p>
              <p className="font-heading font-bold text-3xl tabular-nums" data-testid="documentos-total">
                {euros(dados.resumo.total)}
              </p>
            </div>
            <p className="text-sm text-muted-foreground">
              {dados.resumo.faturas} fatura(s) · {dados.resumo.notas_credito} nota(s) de crédito
            </p>
            {/* As NC já vêm subtraídas do total. Dizê-lo evita a pergunta de
                quem soma a coluna à mão e não bate. */}
            {dados.resumo.notas_credito > 0 && (
              <p className="text-xs text-muted-foreground">
                As notas de crédito estão subtraídas ao faturado.
              </p>
            )}
            {dados.resumo.truncado && (
              <p className="text-sm text-warning flex items-center gap-1.5">
                <AlertTriangle className="h-4 w-4" />
                Muitos documentos para somar de uma vez — reduza o intervalo.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {carregando ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : dados.documentos.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <FileText className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Nenhum documento</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Não há faturas emitidas com estes filtros.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Data</TableHead>
                    <TableHead>Número</TableHead>
                    <TableHead>Loja</TableHead>
                    <TableHead>Cliente</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dados.documentos.map((d) => (
                    <TableRow
                      key={d.id}
                      className="cursor-pointer"
                      onClick={() => abrir(d)}
                      data-testid={`documento-${d.id}`}
                    >
                      <TableCell className="text-muted-foreground">{formatarData(d.emitido_em)}</TableCell>
                      <TableCell className="font-medium">{d.numero || '—'}</TableCell>
                      <TableCell className="text-muted-foreground">{nomeDaLoja(d.loja_id)}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {d.cliente_nif || 'Consumidor Final'}
                      </TableCell>
                      <TableCell>
                        {d.tipo === 'NC'
                          ? <Badge variant="outline" className="bg-rose-50 text-rose-700 border-rose-200">Nota de crédito</Badge>
                          : <Badge variant="outline">Fatura</Badge>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium">
                        {d.tipo === 'NC' ? `− ${euros(d.total)}` : euros(d.total)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {paginas > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button variant="outline" disabled={pagina <= 1 || carregando}
            onClick={() => procurar(pagina - 1)} data-testid="documentos-anterior">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground tabular-nums">
            Página {pagina} de {paginas} · {dados.total} documentos
          </span>
          <Button variant="outline" disabled={pagina >= paginas || carregando}
            onClick={() => procurar(pagina + 1)} data-testid="documentos-seguinte">
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      <Dialog open={!!aberto || aAbrir} onOpenChange={(o) => { if (!o) setAberto(null); }}>
        <DialogContent data-testid="documento-dialog">
          <DialogHeader>
            <DialogTitle>{aberto?.numero || 'A abrir…'}</DialogTitle>
            <DialogDescription>
              {aberto ? `${formatarData(aberto.emitido_em)} · ${aberto.cliente_nif || 'Consumidor Final'}` : ''}
            </DialogDescription>
          </DialogHeader>
          {aberto && (
            <div className="space-y-4">
              {/* O carimbo do MODO daquele documento, não o de agora: um
                  documento emitido em testes não vale nada e o ecrã tem de o
                  dizer (mesma regra da faixa do POS). */}
              {aberto.modo === 'tests' && (
                <p className="text-sm text-warning flex items-center gap-1.5">
                  <AlertTriangle className="h-4 w-4" />
                  Emitido em modo de testes — não foi entregue à Autoridade Tributária.
                </p>
              )}
              <div className="rounded-xl border divide-y">
                {(aberto.linhas || []).map((li, i) => (
                  <div key={i} className="flex items-baseline justify-between gap-3 p-3">
                    <span className="min-w-0">
                      <span className="block">{li.titulo}</span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        {li.quantidade} × {euros(li.preco_unitario)}
                        {li.desconto > 0 && ` · desconto ${euros(li.desconto)}`}
                      </span>
                    </span>
                    <span className="tabular-nums shrink-0">{euros(li.total)}</span>
                  </div>
                ))}
              </div>
              <div className="rounded-xl border divide-y text-sm">
                {(aberto.mapa_imposto || []).map((linha, i) => (
                  <div key={i} className="flex justify-between gap-3 p-2 tabular-nums">
                    <span>IVA {linha.taxa}%</span>
                    <span className="text-muted-foreground">
                      base {euros(linha.base)} · iva {euros(linha.iva)}
                    </span>
                    <span>{euros(linha.total)}</span>
                  </div>
                ))}
              </div>
              <div className="flex items-baseline justify-between">
                <span className="font-medium">Total</span>
                <span className="font-heading font-bold text-2xl tabular-nums">{euros(aberto.total)}</span>
              </div>
              {aberto.total_divergente && (
                <p className="text-sm text-warning flex items-center gap-1.5">
                  <AlertTriangle className="h-4 w-4" />
                  A soma das linhas ({euros(aberto.total_das_linhas)}) não bate com o total do
                  documento. Chame quem trata do sistema.
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
