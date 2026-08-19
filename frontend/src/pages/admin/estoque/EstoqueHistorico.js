import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueLojas, getEstoqueHistorico } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const fmt = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '';
  return (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)).replace('.', ',');
};

// tipo -> rótulo + sinal + cor
const TIPOS = {
  entrada: { label: 'Entrada', cls: 'text-emerald-600', sig: '+' },
  saida: { label: 'Saída', cls: 'text-destructive', sig: '−' },
  contagem: { label: 'Contagem', cls: 'text-blue-600', sig: '=' },
  transferencia_saida: { label: 'Transf. saiu', cls: 'text-destructive', sig: '−' },
  transferencia_entrada: { label: 'Transf. entrou', cls: 'text-emerald-600', sig: '+' },
};

const dataFmt = (s) => {
  if (!s) return '';
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-PT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export default function EstoqueHistorico() {
  const [lojas, setLojas] = useState([]);
  const [lojaId, setLojaId] = useState('');
  const [dias, setDias] = useState('30');
  const [items, setItems] = useState([]);
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
      const r = await getEstoqueHistorico(lojaId, Number(dias));
      setItems(r.data?.items || []);
    } catch {
      toast.error('Não foi possível carregar o histórico.');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [lojaId, dias]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Histórico" subtitle="Movimentos recentes, por loja.">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={lojaId} onValueChange={setLojaId}>
            <SelectTrigger className="w-44"><SelectValue placeholder="Loja" /></SelectTrigger>
            <SelectContent>
              {lojas.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={dias} onValueChange={setDias}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="7">7 dias</SelectItem>
              <SelectItem value="30">30 dias</SelectItem>
              <SelectItem value="90">90 dias</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading && items.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : items.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Sem movimentos no período.</p>
          ) : (
            <div className="divide-y">
              {items.map((m) => {
                const t = TIPOS[m.tipo] || { label: m.tipo, cls: 'text-foreground', sig: '' };
                return (
                  <div key={m.id} className="p-4 flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{m.produto_nome}</p>
                      <p className="text-xs text-muted-foreground">
                        {t.label}
                        {m.autor ? ` · ${m.autor}` : ''}
                        {m.quantidade_antes != null && m.quantidade_depois != null
                          ? ` · ${fmt(m.quantidade_antes)} → ${fmt(m.quantidade_depois)}`
                          : ''}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className={`text-sm font-bold ${t.cls}`}>
                        {t.sig} {fmt(m.quantidade)} {m.unidade_medida}
                      </p>
                      <p className="text-xs text-muted-foreground">{dataFmt(m.data)}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
