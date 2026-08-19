import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueLojas, getEstoqueStock } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Boxes, Store, AlertTriangle, Search } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';
import MovimentoDialog from './MovimentoDialog';

// Número curto e localizado (5.0 -> "5", 2.5 -> "2,5").
const fmt = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '0';
  const s = Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  return s.replace('.', ',');
};

// Limites do produto nesta loja. O mínimo já não se escreve à mão no Estoque: é
// uma percentagem do máximo, definida por marca. Enquanto uma loja não preencher
// o máximo vale o mínimo antigo — e isso tem de se ver também aqui.
const limitesLabel = (i) => {
  const medida = i.unidade_medida || '';
  // `maximo` nulo conta como falta de máximo: os dois deploys (estoque e RH)
  // não aterram ao mesmo tempo e, com o payload antigo, o ramo de baixo
  // anunciava "máx. 0" e uma regra de 30% que ainda não estava a correr.
  if (i.falta_maximo || i.maximo == null) {
    const mn = Number(i.minimo) || 0;
    return mn > 0 ? `mín. ${fmt(mn)} ${medida} · falta o máximo` : 'falta o máximo';
  }
  const pct = Math.round((i.minimo_pct ?? 0.3) * 100);
  return `máx. ${fmt(i.maximo)} ${medida} · avisa a ${fmt(i.minimo)} (${pct}%)`;
};

// Estoque · Stock — stock por loja, puxado do sistema de Estoque (BD separada)
// através do proxy do backend RH (/api/estoque/*). Só leitura (Fase 1).
export default function EstoqueStock() {
  const [lojas, setLojas] = useState([]);
  const [lojaId, setLojaId] = useState('');
  const [itens, setItens] = useState([]);
  const [busca, setBusca] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingLojas, setLoadingLojas] = useState(true);
  const [sel, setSel] = useState(null); // produto selecionado -> painel de movimento

  useEffect(() => {
    getEstoqueLojas()
      .then((r) => {
        const ls = r.data || [];
        setLojas(ls);
        setLojaId((cur) => cur || ls[0]?.id || '');
      })
      .catch(() => toast.error('Não foi possível carregar as lojas do Estoque.'))
      .finally(() => setLoadingLojas(false));
  }, []);

  const load = useCallback(async () => {
    if (!lojaId) return;
    setLoading(true);
    try {
      const r = await getEstoqueStock(lojaId);
      setItens(r.data || []);
    } catch {
      toast.error('Não foi possível carregar o stock desta loja.');
      setItens([]);
    } finally {
      setLoading(false);
    }
  }, [lojaId]);

  useEffect(() => {
    load();
  }, [load]);

  const lojaNome = lojas.find((l) => l.id === lojaId)?.nome || '';
  const filtrados = itens.filter(
    (i) => !busca.trim() || (i.nome || '').toLowerCase().includes(busca.trim().toLowerCase()),
  );
  const abaixo = itens.filter((i) => i.abaixo_minimo).length;

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Stock" subtitle="Stock por loja, do sistema de Estoque.">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={lojaId} onValueChange={setLojaId}>
            <SelectTrigger className="w-48" data-testid="estoque-stock-loja">
              <SelectValue placeholder="Loja" />
            </SelectTrigger>
            <SelectContent>
              {lojas.map((l) => (
                <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </PageHeader>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card>
          <CardContent className="flex items-center gap-3 p-5">
            <div className="h-10 w-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center shrink-0">
              <Boxes className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xl font-heading font-bold leading-none">{itens.length}</p>
              <p className="text-xs text-muted-foreground mt-1">Produtos em stock</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-5">
            <div className="h-10 w-10 rounded-xl bg-destructive/10 text-destructive flex items-center justify-center shrink-0">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xl font-heading font-bold leading-none">{abaixo}</p>
              <p className="text-xs text-muted-foreground mt-1">Abaixo do mínimo</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          className="w-full h-10 rounded-md border border-input bg-background pl-9 pr-3 text-sm"
          placeholder="Procurar produto…"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          data-testid="estoque-stock-busca"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {loadingLojas || (loading && itens.length === 0) ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : !lojaId ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Sem lojas no sistema de Estoque.</p>
          ) : filtrados.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">
              {itens.length === 0
                ? `Sem stock em ${lojaNome}.`
                : 'Nenhum produto corresponde à procura.'}
            </p>
          ) : (
            <div className="divide-y">
              {filtrados.map((i) => (
                <div
                  key={i.produto_id}
                  className="p-4 flex items-center gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => setSel(i)}
                  role="button"
                  tabIndex={0}
                  data-testid={`estoque-stock-${i.produto_id}`}
                >
                  <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center shrink-0 overflow-hidden">
                    {i.foto ? (
                      <img src={i.foto} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <Store className="h-4 w-4 text-muted-foreground" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{i.nome}</p>
                    <p className="text-xs text-muted-foreground">
                      {limitesLabel(i)}
                      {i.fornecedor ? ` · ${i.fornecedor}` : ''}
                    </p>
                  </div>
                  <div className="text-right shrink-0 flex items-center gap-2">
                    {i.abaixo_minimo && <Badge className="bg-destructive hover:bg-destructive">Abaixo</Badge>}
                    <p className={`text-sm font-bold ${i.abaixo_minimo ? 'text-destructive' : ''}`}>
                      {fmt(i.quantidade_atual)} {i.unidade_medida}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {sel && (
        <MovimentoDialog
          item={sel}
          lojaId={lojaId}
          lojaNome={lojaNome}
          lojas={lojas}
          onClose={() => setSel(null)}
          onDone={load}
        />
      )}
    </div>
  );
}
