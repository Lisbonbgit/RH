import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueProdutos, getEstoqueReceita, setEstoqueReceita } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../components/ui/dialog';
import { ClipboardList, Plus, X } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCAS = [
  ['lacai', "L'açaí"],
  ['lenha_brasa', 'Lenha e Brasa'],
  ['purple', 'Purple House'],
];
const parseNum = (v) => {
  const n = Number(String(v ?? '').trim().replace(',', '.'));
  return Number.isFinite(n) ? n : NaN;
};
const fmt = (n) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100)).replace('.', ',');

// Editor da ficha técnica de um produto (rendimento + ingredientes + baldes).
function ReceitaDialog({ produto, produtos, onClose, onSaved }) {
  const [rendimento, setRendimento] = useState('');
  const [ingredientes, setIngredientes] = useState([]); // [{produto_id, quantidade}]
  const [baldes, setBaldes] = useState([]); // [kg]
  const [novoBalde, setNovoBalde] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getEstoqueReceita(produto.id)
      .then((r) => {
        const d = r.data || {};
        setRendimento(d.rendimento != null ? fmt(d.rendimento) : '');
        setIngredientes((d.ingredientes || []).map((i) => ({ produto_id: i.produto_id, quantidade: fmt(i.quantidade) })));
        setBaldes(d.tamanhos_balde || []);
      })
      .catch(() => {});
  }, [produto.id]);

  const outros = produtos.filter((p) => p.id !== produto.id);
  const medida = (id) => produtos.find((p) => p.id === id)?.unidade_medida || '';

  const addIng = () => setIngredientes((s) => [...s, { produto_id: '', quantidade: '' }]);
  const setIng = (i, k, v) => setIngredientes((s) => s.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const rmIng = (i) => setIngredientes((s) => s.filter((_, j) => j !== i));

  const toggleBalde = (kg) => setBaldes((s) => (s.includes(kg) ? s.filter((x) => x !== kg) : [...s, kg].sort((a, b) => a - b)));
  const addBalde = () => {
    const g = parseNum(novoBalde);
    if (Number.isNaN(g) || g <= 0) return;
    const kg = g / 1000; // o campo é em gramas
    if (!baldes.includes(kg)) setBaldes((s) => [...s, kg].sort((a, b) => a - b));
    setNovoBalde('');
  };

  async function guardar() {
    const rend = parseNum(rendimento);
    if (Number.isNaN(rend) || rend <= 0) return toast.error('Indica o rendimento (quanto faz).');
    const ings = [];
    for (const i of ingredientes) {
      if (!i.produto_id) return toast.error('Escolhe todos os ingredientes.');
      const q = parseNum(i.quantidade);
      if (Number.isNaN(q) || q <= 0) return toast.error('Quantidade de ingrediente inválida.');
      ings.push({ produto_id: i.produto_id, quantidade: q });
    }
    setSaving(true);
    try {
      await setEstoqueReceita(produto.id, { rendimento: rend, ingredientes: ings, tamanhos_balde: baldes });
      toast.success('Ficha técnica guardada.');
      onSaved();
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível guardar.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Ficha técnica — {produto.nome}</DialogTitle>
          <DialogDescription>Os ingredientes que esta receita gasta (todos da mesma marca).</DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label>Esta receita faz</Label>
          <div className="flex items-center gap-2">
            <Input inputMode="decimal" value={rendimento} onChange={(e) => setRendimento(e.target.value)} className="w-28" placeholder="10" />
            <span className="text-sm text-muted-foreground">{produto.unidade_medida} de {produto.nome}</span>
          </div>
        </div>

        <div className="space-y-2">
          <Label>Ingredientes</Label>
          {ingredientes.map((ing, i) => (
            <div key={i} className="flex items-center gap-2">
              <Select value={ing.produto_id} onValueChange={(v) => setIng(i, 'produto_id', v)}>
                <SelectTrigger className="flex-1"><SelectValue placeholder="Ingrediente" /></SelectTrigger>
                <SelectContent>
                  {outros.map((p) => <SelectItem key={p.id} value={p.id}>{p.nome}</SelectItem>)}
                </SelectContent>
              </Select>
              <Input inputMode="decimal" value={ing.quantidade} onChange={(e) => setIng(i, 'quantidade', e.target.value)} className="w-20" placeholder="Qtd" />
              <span className="text-xs text-muted-foreground w-8">{medida(ing.produto_id)}</span>
              <Button type="button" variant="ghost" size="icon" className="shrink-0 text-destructive" onClick={() => rmIng(i)}><X className="h-4 w-4" /></Button>
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" onClick={addIng}><Plus className="h-4 w-4 mr-1" /> Adicionar ingrediente</Button>
        </div>

        <div className="space-y-2">
          <Label>Tamanhos de balde</Label>
          <div className="flex flex-wrap items-center gap-2">
            {[0.9, 4.5].map((kg) => (
              <button
                key={kg}
                type="button"
                onClick={() => toggleBalde(kg)}
                className={`text-xs font-medium rounded-full px-3 py-1.5 border ${baldes.includes(kg) ? 'bg-primary text-primary-foreground border-primary' : 'border-input text-muted-foreground'}`}
              >
                {kg < 1 ? `${fmt(kg * 1000)} g` : `${fmt(kg)} kg`}
              </button>
            ))}
            {baldes.filter((b) => b !== 0.9 && b !== 4.5).map((kg) => (
              <button key={kg} type="button" onClick={() => toggleBalde(kg)} className="text-xs font-medium rounded-full px-3 py-1.5 border bg-primary text-primary-foreground border-primary">
                {kg < 1 ? `${fmt(kg * 1000)} g` : `${fmt(kg)} kg`} ✕
              </button>
            ))}
            <div className="flex items-center gap-1">
              <Input inputMode="decimal" value={novoBalde} onChange={(e) => setNovoBalde(e.target.value)} placeholder="gramas" className="w-24 h-8" />
              <Button type="button" variant="outline" size="sm" onClick={addBalde}>+ tamanho</Button>
            </div>
          </div>
        </div>

        <Button onClick={guardar} disabled={saving} className="w-full mt-2">Guardar ficha técnica</Button>
      </DialogContent>
    </Dialog>
  );
}

export default function EstoqueFichas() {
  const [marca, setMarca] = useState('lacai');
  const [produtos, setProdutos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoqueProdutos(marca);
      setProdutos(r.data || []);
    } catch {
      toast.error('Não foi possível carregar o catálogo.');
      setProdutos([]);
    } finally {
      setLoading(false);
    }
  }, [marca]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Fichas técnicas" subtitle="A receita de cada produto (ingredientes que gasta ao produzir).">
        <Select value={marca} onValueChange={setMarca}>
          <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
          <SelectContent>
            {MARCAS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
          </SelectContent>
        </Select>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading && produtos.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : produtos.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Sem produtos nesta marca.</p>
          ) : (
            <div className="divide-y">
              {produtos.map((p) => (
                <div
                  key={p.id}
                  className="p-4 flex items-center gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => setSel(p)}
                  role="button"
                  tabIndex={0}
                >
                  <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center shrink-0">
                    <ClipboardList className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{p.nome}</p>
                    <p className="text-xs text-muted-foreground">{p.unidade_medida}</p>
                  </div>
                  {p.tem_receita ? (
                    <Badge variant="outline" className="shrink-0">com receita</Badge>
                  ) : (
                    <span className="text-xs text-muted-foreground shrink-0">sem receita</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {sel && <ReceitaDialog produto={sel} produtos={produtos} onClose={() => setSel(null)} onSaved={load} />}
    </div>
  );
}
