import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueLojas, getEstoqueProdutos, getEstoqueReceita, estoqueProduzir, getEstoqueProducao } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Factory } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const fmt = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '0';
  return (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)).replace('.', ',');
};
const parseNum = (v) => {
  const n = Number(String(v ?? '').trim().replace(',', '.'));
  return Number.isFinite(n) ? n : NaN;
};
// peso do balde em kg (do peso_valor/peso_unidade do produto)
const baldeKg = (p) => {
  const v = Number(p?.peso_valor);
  if (!Number.isFinite(v) || v <= 0) return null;
  const u = (p?.peso_unidade || '').toLowerCase();
  if (u === 'kg') return v;
  if (u === 'g') return v / 1000;
  return null;
};
const dataFmt = (s) => {
  if (!s) return '';
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-PT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export default function EstoqueProducao() {
  const [fabricas, setFabricas] = useState([]);
  const [fabId, setFabId] = useState('');
  const [produtos, setProdutos] = useState([]);
  const [produtoId, setProdutoId] = useState('');
  const [receita, setReceita] = useState(null);
  const [kg, setKg] = useState('');
  const [saving, setSaving] = useState(false);
  const [relatorio, setRelatorio] = useState([]);

  useEffect(() => {
    getEstoqueLojas()
      .then((r) => {
        const fs = (r.data || []).filter((l) => l.fabrica);
        setFabricas(fs);
        setFabId((cur) => cur || fs[0]?.id || '');
      })
      .catch(() => toast.error('Não foi possível carregar as fábricas.'));
  }, []);

  const marca = fabricas.find((f) => f.id === fabId)?.marca;

  const carregar = useCallback(async () => {
    if (!fabId || !marca) return;
    try {
      const [p, rel] = await Promise.all([getEstoqueProdutos(marca), getEstoqueProducao(fabId, 30)]);
      setProdutos((p.data || []).filter((x) => x.tem_receita));
      setRelatorio(rel.data?.items || []);
    } catch {
      setProdutos([]);
      setRelatorio([]);
    }
    setProdutoId('');
    setReceita(null);
    setKg('');
  }, [fabId, marca]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  useEffect(() => {
    if (!produtoId) {
      setReceita(null);
      return;
    }
    getEstoqueReceita(produtoId).then((r) => setReceita(r.data)).catch(() => setReceita(null));
  }, [produtoId]);

  const prod = produtos.find((p) => p.id === produtoId);
  const bkg = baldeKg(prod);
  const kgNum = parseNum(kg);
  const podePreVer = receita && bkg && !Number.isNaN(kgNum) && kgNum > 0 && receita.rendimento > 0;
  const baldes = podePreVer ? kgNum / bkg : 0;
  const factor = podePreVer ? kgNum / receita.rendimento : 0;

  async function produzir() {
    if (!produtoId) return toast.error('Escolhe o produto.');
    if (!bkg) return toast.error('Este produto não tem peso de balde definido.');
    if (Number.isNaN(kgNum) || kgNum <= 0) return toast.error('Indica os kg produzidos.');
    setSaving(true);
    try {
      await estoqueProduzir(fabId, { produto_id: produtoId, quantidade_kg: kgNum });
      toast.success(`Produzido: ${fmt(baldes)} baldes de ${prod.nome}.`);
      setKg('');
      carregar();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível registar a produção.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Produção" subtitle="Registar a produção da fábrica (gasta ingredientes, cria os baldes).">
        <Select value={fabId} onValueChange={setFabId}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Fábrica" /></SelectTrigger>
          <SelectContent>
            {fabricas.map((f) => <SelectItem key={f.id} value={f.id}>{f.nome}</SelectItem>)}
          </SelectContent>
        </Select>
      </PageHeader>

      {fabricas.length === 0 ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          Nenhuma unidade está marcada como fábrica. (Marca-a em Unidades.)
        </CardContent></Card>
      ) : (
        <Card className="max-w-xl">
          <CardContent className="p-5 space-y-4">
            <div className="space-y-1.5">
              <Label>Produto (com ficha técnica)</Label>
              <Select value={produtoId} onValueChange={setProdutoId}>
                <SelectTrigger><SelectValue placeholder={produtos.length ? 'Escolhe o produto' : 'Sem produtos com receita nesta marca'} /></SelectTrigger>
                <SelectContent>
                  {produtos.map((p) => <SelectItem key={p.id} value={p.id}>{p.nome}</SelectItem>)}
                </SelectContent>
              </Select>
              {prod && !bkg && (
                <p className="text-xs text-destructive">Define o peso do balde neste produto (ex.: 4,5 kg) para poder produzir.</p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label>Quantidade produzida (kg)</Label>
              <Input inputMode="decimal" placeholder="0" value={kg} onChange={(e) => setKg(e.target.value)} className="w-40" />
            </div>

            {podePreVer && (
              <div className="rounded-lg border bg-muted/40 p-3 text-sm space-y-1">
                <p><b>{fmt(baldes)}</b> baldes de {fmt(bkg)} kg</p>
                {receita.ingredientes?.length > 0 && (
                  <p className="text-destructive text-xs">
                    gasta: {receita.ingredientes.map((i) => `${fmt(i.quantidade * factor)} ${i.unidade_medida} ${i.nome}`).join(' · ')}
                  </p>
                )}
              </div>
            )}

            <Button onClick={produzir} disabled={saving || !podePreVer} className="w-full sm:w-auto">
              <Factory className="h-4 w-4 mr-2" /> Registar produção
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {relatorio.length === 0 ? (
            <p className="text-center text-muted-foreground py-10 text-sm">Sem produção nos últimos 30 dias.</p>
          ) : (
            <div className="divide-y">
              {relatorio.map((r) => (
                <div key={r.id} className="p-4 flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{r.produto_nome}</p>
                    <p className="text-xs text-muted-foreground">
                      {r.autor ? `${r.autor} · ` : ''}{fmt(r.kg)} kg
                      {r.ingredientes?.length ? ` · gastou: ${r.ingredientes.map((i) => `${fmt(i.quantidade)} ${i.unidade_medida} ${i.nome}`).join(', ')}` : ''}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-bold text-emerald-600">+ {fmt(r.baldes)} baldes</p>
                    <p className="text-xs text-muted-foreground">{dataFmt(r.data)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
