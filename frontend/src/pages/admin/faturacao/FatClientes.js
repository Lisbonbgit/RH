import React, { useCallback, useEffect, useState } from 'react';
import {
  getClientes, gravarCliente, getDocumentos, detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Users, Search, Loader2, AlertTriangle } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// **Os clientes que pedem fatura com NIF.**
//
// Não há "criar cliente", e é de propósito: um cliente nasce de uma COMPRA. A
// lista vem dos documentos emitidos; o que se grava aqui é só o que eles não
// sabem — o nome, o contacto e uma nota. O NIF é a chave e não se edita:
// trocá-lo passava as compras de uma pessoa para outra.

const euros = (valor) => `€ ${(Number(valor) || 0).toLocaleString('pt-PT', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})}`;

const formatarData = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('pt-PT', { timeZone: 'Europe/Lisbon' });
};

const fichaVazia = { nome: '', email: '', telefone: '', notas: '' };

export default function FatClientes() {
  const [clientes, setClientes] = useState([]);
  const [truncado, setTruncado] = useState(false);
  const [q, setQ] = useState('');
  const [carregando, setCarregando] = useState(true);
  const [aberto, setAberto] = useState(null);
  const [ficha, setFicha] = useState(fichaVazia);
  const [compras, setCompras] = useState(null);
  const [aGravar, setAGravar] = useState(false);

  const procurar = useCallback(async (termo) => {
    setCarregando(true);
    try {
      const { data } = await getClientes(termo || undefined);
      setClientes(data.clientes || []);
      setTruncado(!!data.truncado);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível carregar os clientes.').mensagem);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { procurar(''); }, [procurar]);

  const abrir = async (cliente) => {
    setAberto(cliente);
    setFicha({
      nome: cliente.nome || '', email: cliente.email || '',
      telefone: cliente.telefone || '', notas: cliente.notas || '',
    });
    setCompras(null);
    try {
      // As faturas dele: é a MESMA rota do ecrã de Documentos, com o NIF na
      // pesquisa. Uma segunda maneira de listar as faturas de alguém acabava a
      // discordar da primeira.
      const { data } = await getDocumentos({ q: cliente.nif });
      setCompras(data.documentos || []);
    } catch (error) {
      setCompras([]);
    }
  };

  const guardar = async () => {
    if (!aberto || aGravar) return;
    setAGravar(true);
    try {
      const { data } = await gravarCliente(aberto.nif, {
        nome: ficha.nome.trim() || null,
        email: ficha.email.trim() || null,
        telefone: ficha.telefone.trim() || null,
        notas: ficha.notas.trim() || null,
      });
      setClientes((lista) => lista.map((c) => (c.nif === data.nif ? { ...c, ...data } : c)));
      setAberto(null);
      toast.success('Cliente guardado.');
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível guardar.').mensagem);
    } finally {
      setAGravar(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader icon={Users} title="Clientes" subtitle="Quem pediu fatura com NIF" />

      <Card>
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="space-y-1 flex-1 min-w-[16rem]">
            <Label htmlFor="clientes-q">NIF ou nome</Label>
            <Input
              id="clientes-q" value={q} placeholder="517542510 ou Padaria"
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') procurar(q); }}
              data-testid="clientes-q"
            />
          </div>
          <Button onClick={() => procurar(q)} disabled={carregando} data-testid="clientes-procurar">
            {carregando ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
            Procurar
          </Button>
        </CardContent>
      </Card>

      {truncado && (
        <p className="text-sm text-warning flex items-center gap-1.5">
          <AlertTriangle className="h-4 w-4" />
          Há mais documentos do que os que se conseguem somar de uma vez — os totais podem
          estar incompletos.
        </p>
      )}

      <Card>
        <CardContent className="p-0">
          {carregando ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : clientes.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Users className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem clientes</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Ainda ninguém pediu fatura com NIF. Um cliente aparece aqui na primeira
                compra em que der o contribuinte — não há nada para criar à mão.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>NIF</TableHead>
                    <TableHead>Nome</TableHead>
                    <TableHead className="text-right">Faturas</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead>Última compra</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {clientes.map((c) => (
                    <TableRow
                      key={c.nif} className="cursor-pointer"
                      onClick={() => abrir(c)} data-testid={`cliente-${c.nif}`}
                    >
                      <TableCell className="font-medium tabular-nums">{c.nif}</TableCell>
                      <TableCell className={c.nome ? '' : 'text-muted-foreground'}>
                        {c.nome || 'Sem nome'}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {c.faturas}
                        {c.notas_credito > 0 && (
                          <span className="text-muted-foreground"> · {c.notas_credito} NC</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{euros(c.total)}</TableCell>
                      <TableCell className="text-muted-foreground">{formatarData(c.ultima_compra_em)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!aberto} onOpenChange={(o) => { if (!o) setAberto(null); }}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="cliente-dialog">
          <DialogHeader>
            <DialogTitle>{aberto?.nome || `NIF ${aberto?.nif || ''}`}</DialogTitle>
            <DialogDescription>
              {aberto && `NIF ${aberto.nif} · ${aberto.faturas} fatura(s) · ${euros(aberto.total)}`}
            </DialogDescription>
          </DialogHeader>

          {aberto && (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="cliente-nome">Nome</Label>
                  <Input id="cliente-nome" value={ficha.nome} maxLength={120}
                    onChange={(e) => setFicha({ ...ficha, nome: e.target.value })}
                    data-testid="cliente-nome" />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="cliente-email">Email</Label>
                  <Input id="cliente-email" value={ficha.email} maxLength={160}
                    onChange={(e) => setFicha({ ...ficha, email: e.target.value })}
                    data-testid="cliente-email" />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="cliente-telefone">Telefone</Label>
                  <Input id="cliente-telefone" value={ficha.telefone} maxLength={40}
                    onChange={(e) => setFicha({ ...ficha, telefone: e.target.value })}
                    data-testid="cliente-telefone" />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="cliente-notas">Notas</Label>
                  <Input id="cliente-notas" value={ficha.notas} maxLength={500}
                    onChange={(e) => setFicha({ ...ficha, notas: e.target.value })}
                    data-testid="cliente-notas" />
                </div>
              </div>
              {/* O NIF não é um campo: é a chave. Dizê-lo evita a pergunta de
                  quem o procura para corrigir. */}
              <p className="text-xs text-muted-foreground">
                O NIF não se edita — é por ele que as compras estão ligadas a este cliente.
              </p>

              <div>
                <p className="font-medium mb-2">Compras</p>
                {compras === null ? (
                  <div className="flex items-center justify-center h-16">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : compras.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Sem faturas no alcance da lista.</p>
                ) : (
                  <div className="rounded-xl border divide-y max-h-64 overflow-y-auto">
                    {compras.map((d) => (
                      <div key={d.id} className="flex items-baseline justify-between gap-3 p-2 text-sm">
                        <span className="text-muted-foreground">{formatarData(d.emitido_em)}</span>
                        <span className="flex-1 min-w-0 truncate">{d.numero}</span>
                        <span className="tabular-nums">
                          {d.tipo === 'NC' ? `− ${euros(d.total)}` : euros(d.total)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setAberto(null)}>Fechar</Button>
            <Button onClick={guardar} disabled={aGravar} data-testid="cliente-guardar">
              {aGravar ? 'A guardar…' : 'Guardar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
