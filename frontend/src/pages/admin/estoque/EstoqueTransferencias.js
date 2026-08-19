import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueLojas, getEstoqueStock, estoqueTransferencia } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { ArrowLeftRight } from 'lucide-react';
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

export default function EstoqueTransferencias() {
  const [lojas, setLojas] = useState([]);
  const [origem, setOrigem] = useState('');
  const [destino, setDestino] = useState('');
  const [stock, setStock] = useState([]);
  const [produtoId, setProdutoId] = useState('');
  const [qtd, setQtd] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getEstoqueLojas()
      .then((r) => {
        const ls = r.data || [];
        setLojas(ls);
        setOrigem((cur) => cur || ls[0]?.id || '');
      })
      .catch(() => toast.error('Não foi possível carregar as lojas.'));
  }, []);

  const carregarStock = useCallback(async () => {
    if (!origem) return;
    try {
      const r = await getEstoqueStock(origem);
      setStock(r.data || []);
    } catch {
      setStock([]);
    }
    setProdutoId('');
  }, [origem]);

  useEffect(() => {
    carregarStock();
  }, [carregarStock]);

  const marca = lojas.find((l) => l.id === origem)?.marca;
  const destinos = lojas.filter((l) => l.id !== origem && l.marca === marca);
  const prod = stock.find((p) => p.produto_id === produtoId);

  async function transferir() {
    if (!produtoId) return toast.error('Escolhe o produto.');
    if (!destino) return toast.error('Escolhe a loja de destino.');
    const q = parseNum(qtd);
    if (Number.isNaN(q) || q <= 0) return toast.error('Quantidade inválida.');
    setSaving(true);
    try {
      await estoqueTransferencia({ unidade_id: origem, destino_unidade_id: destino, produto_id: produtoId, quantidade: q });
      const nome = destinos.find((d) => d.id === destino)?.nome || 'destino';
      toast.success(`${prod?.nome || 'Produto'}: ${fmt(q)} ${prod?.unidade_medida || ''} para ${nome}.`);
      setQtd('');
      carregarStock();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível transferir.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Transferências" subtitle="Mover stock de uma loja para outra da mesma marca." />

      <Card className="max-w-xl">
        <CardContent className="p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Loja de origem</Label>
              <Select value={origem} onValueChange={setOrigem}>
                <SelectTrigger><SelectValue placeholder="Origem" /></SelectTrigger>
                <SelectContent>
                  {lojas.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Loja de destino</Label>
              <Select value={destino} onValueChange={setDestino}>
                <SelectTrigger><SelectValue placeholder={destinos.length ? 'Destino' : 'Sem outra loja da marca'} /></SelectTrigger>
                <SelectContent>
                  {destinos.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Produto</Label>
            <Select value={produtoId} onValueChange={setProdutoId}>
              <SelectTrigger><SelectValue placeholder={stock.length ? 'Escolhe o produto' : 'Sem stock na origem'} /></SelectTrigger>
              <SelectContent>
                {stock.map((p) => (
                  <SelectItem key={p.produto_id} value={p.produto_id}>
                    {p.nome} ({fmt(p.quantidade_atual)} {p.unidade_medida})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {prod && (
              <p className="text-xs text-muted-foreground">Disponível: {fmt(prod.quantidade_atual)} {prod.unidade_medida}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label>Quantidade</Label>
            <Input inputMode="decimal" placeholder="0" value={qtd} onChange={(e) => setQtd(e.target.value)} className="w-40" />
          </div>

          <Button onClick={transferir} disabled={saving} className="w-full sm:w-auto">
            <ArrowLeftRight className="h-4 w-4 mr-2" /> Transferir
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
