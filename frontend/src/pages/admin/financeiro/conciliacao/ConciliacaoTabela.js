import React, { useState } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../../components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../../components/ui/select';
import { Input } from '../../../../components/ui/input';
import { Button } from '../../../../components/ui/button';
import { Badge } from '../../../../components/ui/badge';
import { Paperclip, Link2, Trash2, Pencil } from 'lucide-react';
import { eur, fmtDate } from '../../../../lib/finance';
import { descricaoDoMovimento } from '../../../../lib/conciliacao';

const SEM_CATEGORIA = '__sem__';

// Célula de texto que só vira campo quando se clica nela (mesmo gesto da
// justificação no Extrato).
function CelulaTexto({ valor, placeholder, podeEditar, aoGuardar, testid }) {
  const [aEditar, setAEditar] = useState(false);
  const [texto, setTexto] = useState(valor || '');
  if (!podeEditar) return <span className="text-sm">{valor || ''}</span>;
  if (!aEditar) {
    return (
      <button type="button" onClick={() => { setTexto(valor || ''); setAEditar(true); }}
        className="text-left text-sm hover:underline decoration-dotted w-full"
        data-testid={testid}>
        {valor || <span className="text-muted-foreground">{placeholder}</span>}
      </button>
    );
  }
  const fechar = () => { setAEditar(false); if ((valor || '') !== texto) aoGuardar(texto); };
  return (
    <Input autoFocus value={texto} className="h-8 text-sm"
      onChange={(e) => setTexto(e.target.value)}
      onBlur={fechar}
      onKeyDown={(e) => {
        if (e.key === 'Enter') fechar();
        if (e.key === 'Escape') setAEditar(false);
      }} />
  );
}

export default function ConciliacaoTabela({ movimentos, categorias, podeEditar, aoGuardar, aoApagar, aoAbrirFaturas }) {
  if (!movimentos.length) {
    return <p className="text-center text-muted-foreground py-10">Sem movimentos neste mês.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-24">Data</TableHead>
            <TableHead className="w-40">Categoria</TableHead>
            <TableHead>Descrição</TableHead>
            <TableHead className="text-right w-32">Montante</TableHead>
            <TableHead className="w-44">Faturas</TableHead>
            <TableHead className="hidden lg:table-cell">Anotações</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {movimentos.map((mv) => (
            <TableRow key={mv.id} data-testid={`fin-conc-row-${mv.id}`}>
              <TableCell className="whitespace-nowrap text-sm">{fmtDate(mv.date_lancamento)}</TableCell>
              <TableCell>
                {podeEditar ? (
                  <Select value={mv.category || SEM_CATEGORIA}
                    onValueChange={(v) => aoGuardar(mv, { category: v === SEM_CATEGORIA ? null : v })}>
                    <SelectTrigger className="h-8 w-36 text-xs" data-testid={`fin-conc-cat-${mv.id}`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={SEM_CATEGORIA}>Sem categoria</SelectItem>
                      {categorias.map((c) => <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                ) : (
                  <span className="text-sm">{mv.category || '—'}</span>
                )}
              </TableCell>
              <TableCell>
                <CelulaTexto valor={mv.title} placeholder={descricaoDoMovimento(mv)} podeEditar={podeEditar}
                  testid={`fin-conc-desc-${mv.id}`}
                  aoGuardar={(t) => aoGuardar(mv, { title: t })} />
                {mv.manual && <Badge variant="outline" className="ml-2 text-[10px]">à mão</Badge>}
                {mv.title && mv.description && (
                  <p className="text-[11px] text-muted-foreground truncate">{mv.description}</p>
                )}
              </TableCell>
              <TableCell className={`text-right whitespace-nowrap tabular-nums ${
                (Number(mv.amount) || 0) < 0 ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}`}>
                {eur(mv.amount)}
              </TableCell>
              <TableCell>
                <Button variant="ghost" size="sm" className="h-8 px-2"
                  onClick={() => aoAbrirFaturas(mv)} data-testid={`fin-conc-doc-${mv.id}`}>
                  {mv.invoice_id
                    ? <><Link2 className="h-3.5 w-3.5 mr-1 text-emerald-600" /><span className="text-xs">Ligada</span></>
                    : mv.attachment_path
                      ? <><Paperclip className="h-3.5 w-3.5 mr-1" /><span className="text-xs">Anexo</span></>
                      : <><Pencil className="h-3.5 w-3.5 mr-1 opacity-50" /><span className="text-xs text-muted-foreground">Ligar</span></>}
                </Button>
              </TableCell>
              <TableCell className="hidden lg:table-cell">
                <CelulaTexto valor={mv.note} placeholder="—" podeEditar={podeEditar}
                  testid={`fin-conc-nota-${mv.id}`}
                  aoGuardar={(t) => aoGuardar(mv, { note: t })} />
              </TableCell>
              <TableCell>
                {podeEditar && mv.manual && (
                  <Button variant="ghost" size="icon" className="h-8 w-8" title="Apagar linha"
                    onClick={() => aoApagar(mv)} data-testid={`fin-conc-del-${mv.id}`}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
