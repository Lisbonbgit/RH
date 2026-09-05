import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { toast } from 'sonner';
import { Scale, Plus } from 'lucide-react';
import PageHeader from '../../../../components/PageHeader';
import MonthPicker from '../../../../components/MonthPicker';
import { Card, CardContent } from '../../../../components/ui/card';
import { Button } from '../../../../components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../../components/ui/tabs';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '../../../../components/ui/dialog';
import { Input } from '../../../../components/ui/input';
import { Label } from '../../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../../components/ui/select';
import {
  getFinMovements, updateFinMovement, createFinMovement, deleteFinMovement,
  getFinBankBalances, getFinReconcilePending,
} from '../../../../lib/api';
import { categoriasDaEmpresa, todayISO } from '../../../../lib/finance';
import ConciliacaoTabela from './ConciliacaoTabela';
import ConciliacaoCartoes from './ConciliacaoCartoes';
import ConciliacaoSugestoes from './ConciliacaoSugestoes';
import DialogoFatura from './DialogoFatura';

const mesAtual = () => todayISO().slice(0, 7);

export default function FinConciliacao() {
  const { selectedCompany } = useOutletContext();
  const [month, setMonth] = useState(mesAtual());
  const [movimentos, setMovimentos] = useState([]);
  const [saldos, setSaldos] = useState(null);
  const [pendentes, setPendentes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [novaLinha, setNovaLinha] = useState(null);
  const [movDoc, setMovDoc] = useState(null);

  const companyId = selectedCompany ? selectedCompany.id : null;
  const categorias = useMemo(() => categoriasDaEmpresa(selectedCompany), [selectedCompany]);
  const podeEditar = !!selectedCompany && ['owner', 'partner'].includes(selectedCompany.role);

  const carregar = useCallback(async () => {
    if (!companyId) { setMovimentos([]); return; }
    setLoading(true);
    try {
      const { data } = await getFinMovements({ company_id: companyId, month });
      setMovimentos(data || []);
      const [s, p] = await Promise.all([
        getFinBankBalances(companyId).catch(() => ({ data: null })),
        getFinReconcilePending(companyId, month).catch(() => ({ data: null })),
      ]);
      setSaldos(s.data);
      setPendentes(p.data);
    } catch (e) {
      toast.error('Não foi possível carregar os movimentos.');
    } finally {
      setLoading(false);
    }
  }, [companyId, month]);

  useEffect(() => { carregar(); }, [carregar]);

  const guardar = async (mv, campos) => {
    // Otimista: a célula não pode piscar a cada tecla guardada.
    setMovimentos((lista) => lista.map((x) => (x.id === mv.id ? { ...x, ...campos } : x)));
    try {
      await updateFinMovement(mv.id, campos);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível guardar.');
      carregar();
    }
  };

  const apagar = async (mv) => {
    try {
      await deleteFinMovement(mv.id);
      setMovimentos((lista) => lista.filter((x) => x.id !== mv.id));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível apagar.');
    }
  };

  const criar = async () => {
    try {
      await createFinMovement({ ...novaLinha, amount: Number(novaLinha.amount), company_id: companyId });
      setNovaLinha(null);
      carregar();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível criar a linha.');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-conciliacao-page">
      <PageHeader icon={Scale} title="Conciliação"
        subtitle="O mês do banco, classificado e com os documentos ligados">
        <MonthPicker value={month} onChange={setMonth} className="w-44" testid="fin-conc-month" />
        {podeEditar && (
          <Button variant="outline" size="sm" data-testid="fin-conc-nova"
            onClick={() => setNovaLinha({ date_lancamento: `${month}-01`, description: '', amount: '', category: null })}>
            <Plus className="h-4 w-4 mr-2" />Linha
          </Button>
        )}
      </PageHeader>

      <Tabs defaultValue="mapa" className="space-y-4">
        <TabsList>
          <TabsTrigger value="mapa" data-testid="fin-conc-tab-mapa">Mapa do mês</TabsTrigger>
          <TabsTrigger value="sugestoes" data-testid="fin-conc-tab-sugestoes">Sugestões</TabsTrigger>
          <TabsTrigger value="porligar" data-testid="fin-conc-tab-porligar">Por ligar</TabsTrigger>
        </TabsList>

        {/* O mapa é sempre de UMA empresa: sem ela não há saldo contínuo nem
            "Excel" para mostrar. As outras duas vistas agregam todas. */}
        <TabsContent value="mapa" className="space-y-4">
          {!selectedCompany ? (
            <Card><CardContent className="p-6 text-center text-muted-foreground">
              Escolhe uma empresa no topo. Cada empresa tem a sua conciliação.
            </CardContent></Card>
          ) : (
            <>
              <ConciliacaoCartoes movimentos={movimentos} categorias={categorias}
                saldos={saldos} pendentes={pendentes} />
              <Card><CardContent className="p-0">
                {loading
                  ? <div className="flex justify-center h-24 items-center">
                      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                    </div>
                  : <ConciliacaoTabela
                      movimentos={movimentos} categorias={categorias} podeEditar={podeEditar}
                      aoGuardar={guardar} aoApagar={apagar} aoAbrirFaturas={setMovDoc} />}
              </CardContent></Card>
            </>
          )}
        </TabsContent>

        <TabsContent value="sugestoes">
          <ConciliacaoSugestoes vista="sugestoes" companyId={companyId} month={month} aoMudar={carregar} />
        </TabsContent>
        <TabsContent value="porligar">
          <ConciliacaoSugestoes vista="porligar" companyId={companyId} month={month} aoMudar={carregar} />
        </TabsContent>
      </Tabs>

      <Dialog open={!!novaLinha} onOpenChange={(o) => !o && setNovaLinha(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Linha escrita à mão</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Data</Label>
              <Input type="date" value={novaLinha?.date_lancamento || ''}
                onChange={(e) => setNovaLinha({ ...novaLinha, date_lancamento: e.target.value })} /></div>
            <div><Label>Descrição</Label>
              <Input value={novaLinha?.description || ''} placeholder="Dinheiro Restante Mês Anterior"
                onChange={(e) => setNovaLinha({ ...novaLinha, description: e.target.value })} /></div>
            <div><Label>Montante</Label>
              <Input type="number" step="0.01" value={novaLinha?.amount ?? ''}
                placeholder="Negativo se for dinheiro a sair"
                onChange={(e) => setNovaLinha({ ...novaLinha, amount: e.target.value })} /></div>
            <div><Label>Categoria</Label>
              <Select value={novaLinha?.category || ''}
                onValueChange={(v) => setNovaLinha({ ...novaLinha, category: v })}>
                <SelectTrigger><SelectValue placeholder="Escolhe" /></SelectTrigger>
                <SelectContent>
                  {categorias.map((c) => <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>)}
                </SelectContent>
              </Select></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNovaLinha(null)}>Cancelar</Button>
            <Button onClick={criar} data-testid="fin-conc-nova-guardar">Criar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DialogoFatura movimento={movDoc} companyId={companyId} aberto={!!movDoc}
        aoFechar={() => setMovDoc(null)} aoMudar={carregar} />
    </div>
  );
}
