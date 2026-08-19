import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueLojas, getEstoqueListaCompras } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { ShoppingCart } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const fmt = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '0';
  return (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)).replace('.', ',');
};

export default function EstoqueListaCompras() {
  const [lojas, setLojas] = useState([]);
  const [lojaId, setLojaId] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getEstoqueLojas()
      .then((r) => {
        const ls = r.data || [];
        setLojas(ls);
        setLojaId((cur) => cur || ls[0]?.id || '');
      })
      .catch(() => toast.error('Não foi possível carregar as lojas.'));
  }, []);

  const load = useCallback(async () => {
    if (!lojaId) return;
    setLoading(true);
    try {
      const r = await getEstoqueListaCompras(lojaId);
      setData(r.data);
    } catch {
      toast.error('Não foi possível carregar a lista de compras.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [lojaId]);

  useEffect(() => {
    load();
  }, [load]);

  const items = data?.items || [];

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Lista de compras" subtitle="Produtos abaixo do mínimo, por loja.">
        <Select value={lojaId} onValueChange={setLojaId}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Loja" /></SelectTrigger>
          <SelectContent>
            {lojas.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
          </SelectContent>
        </Select>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading && !data ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : items.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">
              Nada abaixo do mínimo nesta loja. 👍
            </p>
          ) : (
            <div className="divide-y">
              {items.map((i) => (
                <div key={i.produto_id} className="p-4 flex items-center gap-3">
                  <div className="h-9 w-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                    <ShoppingCart className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{i.nome}</p>
                    <p className="text-xs text-muted-foreground">
                      tem {fmt(i.quantidade_atual)} · mín. {fmt(i.minimo)} {i.unidade_medida}
                      {i.fornecedor ? ` · ${i.fornecedor}` : ''}
                    </p>
                  </div>
                  <Badge variant="outline" className="shrink-0">
                    comprar {fmt(i.sugestao_compra)} {i.unidade_medida}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
