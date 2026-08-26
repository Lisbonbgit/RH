import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueDefinicoes, simularEstoqueDefinicao, setEstoqueDefinicao } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCA_LABEL = { lacai: "L'açaí", lenha_brasa: 'Lenha e Brasa', purple: 'Purple House' };

function MarcaCard({ m, onSaved }) {
  const [pct, setPct] = useState(String(m.percentagem));
  const [sim, setSim] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setPct(String(m.percentagem)); setSim(null); }, [m.percentagem]);

  const n = Number(pct);
  const valido = Number.isFinite(n) && n >= 10 && n <= 90;
  const mudou = valido && n !== m.percentagem;

  async function simular() {
    if (!valido) return toast.error('A percentagem tem de estar entre 10 e 90.');
    setBusy(true);
    try {
      const r = await simularEstoqueDefinicao(m.marca, n);
      setSim(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível simular.');
    } finally {
      setBusy(false);
    }
  }

  async function guardar() {
    if (!valido) return toast.error('A percentagem tem de estar entre 10 e 90.');
    setBusy(true);
    try {
      await setEstoqueDefinicao(m.marca, n);
      toast.success(`${MARCA_LABEL[m.marca] || m.marca}: mínimo passa a ${n}% do máximo.`);
      setSim(null);
      onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível guardar.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent className="p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium">{MARCA_LABEL[m.marca] || m.marca}</p>
            <p className="text-xs text-muted-foreground">
              {m.total_produtos} produtos · {m.abaixo_minimo} abaixo do mínimo
              {m.sem_maximo > 0 ? ` · ${m.sem_maximo} sem máximo` : ''}
              {m.por_omissao ? ' · (por omissão)' : ''}
            </p>
          </div>
        </div>

        <div className="flex items-end gap-3">
          <div className="space-y-1.5">
            <Label>Mínimo = % do máximo</Label>
            <div className="flex items-center gap-2">
              <Input inputMode="numeric" value={pct} onChange={(e) => setPct(e.target.value)} className="w-24" />
              <span className="text-sm text-muted-foreground">%</span>
            </div>
          </div>
          <Button variant="outline" onClick={simular} disabled={busy || !valido}>Ver efeito</Button>
          <Button onClick={guardar} disabled={busy || !mudou}>Guardar</Button>
        </div>

        {sim && (
          <div className="rounded-lg border bg-muted/40 p-3 text-sm space-y-2">
            <p>
              Passa de <b>{sim.percentagem_atual}%</b> ({sim.abaixo_atual} abaixo) para{' '}
              <b>{sim.percentagem_nova}%</b> (<b>{sim.abaixo_novo}</b> abaixo) — em {sim.total_produtos} produtos.
            </p>
            {sim.passam_a_abaixo?.length > 0 && (
              <p className="text-xs text-destructive">
                Passam a avisar: {sim.passam_a_abaixo.join(', ')}
              </p>
            )}
            {sim.deixam_de_estar_abaixo?.length > 0 && (
              <p className="text-xs text-emerald-600">
                Deixam de avisar: {sim.deixam_de_estar_abaixo.join(', ')}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function EstoqueDefinicoes() {
  const [marcas, setMarcas] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoqueDefinicoes();
      setMarcas(r.data?.marcas || []);
    } catch {
      toast.error('Não foi possível carregar as definições.');
      setMarcas([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Definições" subtitle="O mínimo automático: quando o stock desce abaixo desta % do máximo, avisa." />
      {loading ? (
        <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
      ) : (
        <div className="space-y-4 max-w-2xl">
          {marcas.map((m) => <MarcaCard key={m.marca} m={m} onSaved={load} />)}
        </div>
      )}
    </div>
  );
}
