import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueOverview } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Store, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCA_LABEL = { lacai: "L'açaí", lenha_brasa: 'Lenha e Brasa', purple: 'Purple House' };

export default function EstoqueVisaoGeral() {
  const [lojas, setLojas] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoqueOverview();
      setLojas(r.data || []);
    } catch {
      toast.error('Não foi possível carregar a visão geral.');
      setLojas([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const totalAbaixo = lojas.reduce((a, l) => a + (l.abaixo_minimo || 0), 0);
  const totalSemMax = lojas.reduce((a, l) => a + (l.sem_maximo || 0), 0);
  const totalProd = lojas.reduce((a, l) => a + (l.total_produtos || 0), 0);

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Visão geral" subtitle="O estado do stock em todas as lojas do grupo." />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          ['Lojas', lojas.length],
          ['Produtos (linhas)', totalProd],
          ['Abaixo do mínimo', totalAbaixo],
          ['Sem máximo', totalSemMax],
        ].map(([label, val]) => (
          <div key={label} className="rounded-lg bg-muted/50 p-4">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-2xl font-medium">{val}</p>
          </div>
        ))}
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : lojas.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Sem lojas.</p>
          ) : (
            <div className="divide-y">
              {lojas.map((l) => (
                <div key={l.unidade_id} className="p-4 flex items-center gap-3">
                  <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center shrink-0">
                    <Store className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {l.nome}
                      {!l.ativo && <span className="text-xs text-muted-foreground"> · inativa</span>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {MARCA_LABEL[l.marca] || l.marca} · {l.total_produtos} produtos
                      {l.sem_maximo > 0 ? ` · ${l.sem_maximo} sem máximo` : ''}
                    </p>
                  </div>
                  {l.abaixo_minimo > 0 ? (
                    <Badge variant="destructive" className="shrink-0 gap-1">
                      <AlertTriangle className="h-3 w-3" /> {l.abaixo_minimo} a comprar
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="shrink-0">ok</Badge>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
