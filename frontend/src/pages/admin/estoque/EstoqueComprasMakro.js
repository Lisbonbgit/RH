import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { getEstoqueComprasMakro } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { ShoppingCart, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCA_LABEL = { lacai: "L'açaí", lenha_brasa: 'Lenha e Brasa', purple: 'Purple House' };
const fmt = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '0';
  return (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)).replace('.', ',');
};
const eur = (n) => (Number.isFinite(Number(n)) ? Number(n).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €' : '—');

function Linha({ it, lojaNome, done, onToggle }) {
  // quanto comprar: em packs se houver pack definido, senão no total em unidade de stock
  const comprar = it.packs != null
    ? `${it.packs} ${it.pack_nome || 'pack'}${it.packs === 1 ? '' : 's'}`
    : `${fmt(it.defice_total)} ${it.unidade_medida}`;
  const detalhe = it.packs != null ? `≈ ${fmt(it.defice_total)} ${it.unidade_medida}` : null;
  return (
    <label className={`p-4 flex items-start gap-3 cursor-pointer hover:bg-muted/50 transition-colors ${done ? 'opacity-50' : ''}`}>
      <input type="checkbox" checked={done} onChange={onToggle} className="mt-1 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className={`text-sm font-medium ${done ? 'line-through' : ''}`}>
          {it.nome}
          <span className="text-xs text-muted-foreground font-normal"> · {MARCA_LABEL[it.marca] || it.marca}</span>
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
          <ShoppingCart className="h-3.5 w-3.5 text-muted-foreground" />{comprar}
        </p>
        <p className="text-xs text-muted-foreground">
          {detalhe ? detalhe + ' · ' : ''}{it.custo != null ? eur(it.custo) : 'sem preço'}
        </p>
      </div>
    </label>
  );
}

function Seccao({ titulo, nota, items, lojaNome, feito, setFeito }) {
  if (items.length === 0) return null;
  const subtotal = items.reduce((a, it) => a + (Number(it.custo) || 0), 0);
  const ordenados = [...items].sort((a, b) => (feito[a.produto_id] ? 1 : 0) - (feito[b.produto_id] ? 1 : 0));
  return (
    <Card>
      <CardContent className="p-0">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">{titulo}</p>
            {nota ? <p className="text-xs text-muted-foreground">{nota}</p> : null}
          </div>
          <p className="text-sm font-medium">{eur(subtotal)}</p>
        </div>
        <div className="divide-y">
          {ordenados.map((it) => (
            <Linha key={it.produto_id} it={it} lojaNome={lojaNome} done={!!feito[it.produto_id]}
              onToggle={() => setFeito((s) => ({ ...s, [it.produto_id]: !s[it.produto_id] }))} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function EstoqueComprasMakro() {
  const [data, setData] = useState({ lojas: [], items: [], custo_total: 0 });
  const [loading, setLoading] = useState(true);
  const [feito, setFeito] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoqueComprasMakro();
      setData(r.data || { lojas: [], items: [], custo_total: 0 });
    } catch {
      toast.error('Não foi possível carregar a lista de compras.');
      setData({ lojas: [], items: [], custo_total: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const lojaNome = useMemo(() => {
    const m = {}; (data.lojas || []).forEach((l) => { m[l.unidade_id] = l.nome; }); return m;
  }, [data.lojas]);

  const semanal = (data.items || []).filter((i) => i.cadencia !== 'bissemanal');
  const fruta = (data.items || []).filter((i) => i.cadencia === 'bissemanal');

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Compras Makro" subtitle="Tudo o que falta comprar para encher ao máximo, somado por todas as lojas.">
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className="h-4 w-4 mr-1" /> Atualizar
        </Button>
      </PageHeader>

      {loading ? (
        <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
      ) : (data.items || []).length === 0 ? (
        <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">
          Nada a comprar — tudo no máximo. 🎉<br />
          <span className="text-xs">(Marca os artigos como "de compra" no Catálogo e define o máximo por loja no Stock.)</span>
        </CardContent></Card>
      ) : (
        <>
          <div className="rounded-lg bg-muted/50 p-4 flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Custo estimado total</span>
            <span className="text-2xl font-medium">{eur(data.custo_total)}</span>
          </div>
          <Seccao titulo="Compra da semana (segunda)" items={semanal} lojaNome={lojaNome} feito={feito} setFeito={setFeito} />
          <Seccao titulo="Fruta (2×/semana)" nota="Comprada também a meio da semana." items={fruta} lojaNome={lojaNome} feito={feito} setFeito={setFeito} />
        </>
      )}
    </div>
  );
}
