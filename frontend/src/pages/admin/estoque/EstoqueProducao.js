import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueLojas, getEstoqueProdutos, getEstoqueReceita, estoqueProduzir, getEstoqueProducao, reverterEstoqueProducao } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Badge } from '../../../components/ui/badge';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Factory, Undo2 } from 'lucide-react';
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
  const [completos, setCompletos] = useState('');
  const [incompletos, setIncompletos] = useState('');
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
    setCompletos('');
    setIncompletos('');
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
  const nC = parseNum(completos);
  const nI = incompletos.trim() === '' ? 0 : parseNum(incompletos);
  const completosOk = completos.trim() !== '' && Number.isInteger(nC) && nC >= 0;
  const podePreVer = receita && bkg && !Number.isNaN(kgNum) && kgNum > 0 && receita.rendimento > 0;
  const factor = podePreVer ? kgNum / receita.rendimento : 0;
  // perda/margem = kg − (baldes completos × peso + kg por acabar). Só admin (é esta página).
  const perda = podePreVer && completosOk && !Number.isNaN(nI) ? kgNum - (nC * bkg + nI) : null;
  const podeProduzir = !!bkg && !Number.isNaN(kgNum) && kgNum > 0 && completosOk && !Number.isNaN(nI) && nI >= 0 && (nC > 0 || nI > 0);

  async function produzir() {
    if (!produtoId) return toast.error('Escolhe o produto.');
    if (!bkg) return toast.error('Este produto não tem peso de balde definido.');
    if (Number.isNaN(kgNum) || kgNum <= 0) return toast.error('Indica os kg produzidos.');
    if (!completosOk) return toast.error('Baldes completos: usa um número inteiro (0, 1, 2…).');
    if (Number.isNaN(nI) || nI < 0) return toast.error('Kg por acabar inválido.');
    if (nC === 0 && nI === 0) return toast.error('Indica os baldes completos e/ou os kg por acabar.');
    setSaving(true);
    try {
      await estoqueProduzir(fabId, { produto_id: produtoId, quantidade_kg: kgNum, baldes_completos: nC, kg_incompletos: nI });
      toast.success(`Produzido: ${nC} baldes de ${prod.nome}${nI > 0 ? ` (+ ${fmt(nI)} kg por acabar)` : ''}.`);
      setKg('');
      setCompletos('');
      setIncompletos('');
      carregar();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível registar a produção.');
    } finally {
      setSaving(false);
    }
  }

  async function anular(r) {
    if (!window.confirm(`Anular esta produção de ${r.produto_nome} (${fmt(r.baldes)} baldes)? Os ingredientes voltam ao stock e os baldes são retirados.`)) return;
    setSaving(true);
    try {
      await reverterEstoqueProducao(r.id);
      toast.success('Produção anulada. Fica registada no histórico.');
      carregar();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível anular.');
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
              <Label>Kg produzidos (total)</Label>
              <Input inputMode="decimal" placeholder="ex.: 230" value={kg} onChange={(e) => setKg(e.target.value)} className="w-40" />
            </div>

            <div className="grid grid-cols-2 gap-3 max-w-md">
              <div className="space-y-1.5">
                <Label>Baldes completos</Label>
                <Input inputMode="numeric" placeholder="ex.: 50" value={completos} onChange={(e) => setCompletos(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Kg em baldes por acabar</Label>
                <Input inputMode="decimal" placeholder="ex.: 3" value={incompletos} onChange={(e) => setIncompletos(e.target.value)} />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Só os baldes completos entram no stock. Os kg por acabar terminam-se no dia seguinte.
            </p>

            {podePreVer && (
              <div className="rounded-lg border bg-muted/40 p-3 text-sm space-y-1">
                {receita.ingredientes?.length > 0 && (
                  <p className="text-destructive text-xs">
                    gasta: {receita.ingredientes.map((i) => `${fmt(i.quantidade * factor)} ${i.unidade_medida} ${i.nome}`).join(' · ')}
                  </p>
                )}
                {perda != null && (
                  <p className="text-xs">perda/margem ≈ <b>{fmt(perda)} kg</b> (kg − baldes)</p>
                )}
              </div>
            )}

            <Button onClick={produzir} disabled={saving || !podeProduzir} className="w-full sm:w-auto">
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
                <div key={r.id} className={`p-4 flex items-start gap-3 ${r.revertida ? 'opacity-60' : ''}`}>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium flex items-center gap-2">
                      <span className={r.revertida ? 'line-through' : ''}>{r.produto_nome}</span>
                      {r.revertida && <Badge variant="secondary">anulada</Badge>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {r.autor ? `${r.autor} · ` : ''}{fmt(r.kg)} kg
                      {r.kg_incompletos > 0 ? ` · ${fmt(r.kg_incompletos)} kg por acabar` : ''}
                      {typeof r.perda_kg === 'number' && r.perda_kg !== 0 ? ` · perda ${fmt(r.perda_kg)} kg` : ''}
                      {r.ingredientes?.length ? ` · gastou: ${r.ingredientes.map((i) => `${fmt(i.quantidade)} ${i.unidade_medida} ${i.nome}`).join(', ')}` : ''}
                      {r.revertida && r.revertida_por ? ` · anulada por ${r.revertida_por}` : ''}
                    </p>
                  </div>
                  <div className="text-right shrink-0 flex flex-col items-end gap-1">
                    <p className={`text-sm font-bold ${r.revertida ? 'text-muted-foreground line-through' : 'text-emerald-600'}`}>+ {fmt(r.baldes)} baldes</p>
                    <p className="text-xs text-muted-foreground">{dataFmt(r.data)}</p>
                    {!r.revertida && (
                      <Button variant="ghost" size="sm" className="h-7 text-destructive" disabled={saving} onClick={() => anular(r)}>
                        <Undo2 className="h-3.5 w-3.5 mr-1" /> Anular
                      </Button>
                    )}
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
