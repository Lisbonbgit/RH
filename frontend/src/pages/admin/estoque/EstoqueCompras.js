import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { getEstoqueCompras } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { ShoppingCart } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCAS = [['lacai', "L'açaí"], ['lenha_brasa', 'Lenha e Brasa'], ['purple', 'Purple House']];
const fmt = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '0';
  return (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)).replace('.', ',');
};

export default function EstoqueCompras() {
  const [marca, setMarca] = useState('lacai');
  const [data, setData] = useState({ lojas: [], items: [] });
  const [loading, setLoading] = useState(false);
  const [feito, setFeito] = useState({}); // produto_id -> true (só no ecrã)

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoqueCompras(marca);
      setData(r.data || { lojas: [], items: [] });
    } catch {
      toast.error('Não foi possível carregar as compras.');
      setData({ lojas: [], items: [] });
    } finally {
      setLoading(false);
    }
  }, [marca]);

  useEffect(() => { load(); setFeito({}); }, [load]);

  const lojaNome = useMemo(() => {
    const m = {};
    (data.lojas || []).forEach((l) => { m[l.unidade_id] = l.nome; });
    return m;
  }, [data.lojas]);

  // Por comprar primeiro; os marcados descem para o fim.
  const ordenados = useMemo(() => {
    const items = data.items || [];
    return [...items].sort((a, b) => (feito[a.produto_id] ? 1 : 0) - (feito[b.produto_id] ? 1 : 0));
  }, [data.items, feito]);

  const porComprar = (data.items || []).filter((i) => !feito[i.produto_id]).length;

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Compras" subtitle="Tudo o que está abaixo do mínimo, somado por marca.">
        <Select value={marca} onValueChange={setMarca}>
          <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
          <SelectContent>
            {MARCAS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
          </SelectContent>
        </Select>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : (data.items || []).length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Nada a comprar nesta marca. 🎉</p>
          ) : (
            <>
              <div className="px-4 py-3 border-b text-xs text-muted-foreground">
                {porComprar} por comprar de {(data.items || []).length}
              </div>
              <div className="divide-y">
                {ordenados.map((it) => {
                  const done = !!feito[it.produto_id];
                  return (
                    <label
                      key={it.produto_id}
                      className={`p-4 flex items-start gap-3 cursor-pointer hover:bg-muted/50 transition-colors ${done ? 'opacity-50' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={done}
                        onChange={() => setFeito((s) => ({ ...s, [it.produto_id]: !s[it.produto_id] }))}
                        className="mt-1 h-4 w-4 shrink-0"
                      />
                      <div className="min-w-0 flex-1">
                        <p className={`text-sm font-medium ${done ? 'line-through' : ''}`}>
                          {it.nome}
                          {it.fornecedor ? <span className="text-xs text-muted-foreground font-normal"> · {it.fornecedor}</span> : null}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {Object.entries(it.por_loja || {}).map(([uid, q], i) => (
                            <span key={uid}>{i > 0 ? ' · ' : ''}{lojaNome[uid] || '?'} {fmt(q)}</span>
                          ))}
                        </p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-sm font-bold flex items-center gap-1 justify-end">
                          <ShoppingCart className="h-3.5 w-3.5 text-muted-foreground" />
                          {fmt(it.total)} {it.unidade_medida}
                        </p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
