import React, { useState, useEffect, useCallback } from 'react';
import { getEstoqueUnidades, criarEstoqueUnidade, editarEstoqueUnidade } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../components/ui/dialog';
import { Store, Plus, Factory } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCAS = [['lacai', "L'açaí"], ['lenha_brasa', 'Lenha e Brasa'], ['purple', 'Purple House']];
const marcaLabel = (m) => (MARCAS.find(([v]) => v === m) || [m, m])[1];

function UnidadeDialog({ unidade, onClose, onSaved }) {
  const editar = !!unidade;
  const [nome, setNome] = useState(unidade?.nome || '');
  const [marca, setMarca] = useState(unidade?.marca || 'lacai');
  const [ativo, setAtivo] = useState(unidade ? unidade.ativo : true);
  const [fabrica, setFabrica] = useState(unidade?.fabrica || false);
  const [saving, setSaving] = useState(false);

  async function guardar() {
    if (!nome.trim()) return toast.error('Indica o nome da unidade.');
    setSaving(true);
    try {
      if (editar) {
        await editarEstoqueUnidade(unidade.id, { nome: nome.trim(), ativo, fabrica });
        toast.success('Unidade atualizada.');
      } else {
        await criarEstoqueUnidade({ nome: nome.trim(), marca });
        toast.success('Unidade criada.');
      }
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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{editar ? 'Editar unidade' : 'Nova unidade'}</DialogTitle>
          <DialogDescription>{editar ? `${unidade.nome} · ${marcaLabel(unidade.marca)}` : 'Uma loja ou fábrica de uma marca.'}</DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label>Nome</Label>
          <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: Alfragide" />
        </div>

        {!editar && (
          <div className="space-y-1.5">
            <Label>Marca</Label>
            <Select value={marca} onValueChange={setMarca}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{MARCAS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">A marca não muda depois de criada.</p>
          </div>
        )}

        {editar && (
          <div className="space-y-2 pt-1">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={ativo} onChange={(e) => setAtivo(e.target.checked)} className="h-4 w-4" />
              Ativa
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={fabrica} onChange={(e) => setFabrica(e.target.checked)} className="h-4 w-4" />
              É fábrica (produz — mostra o módulo de produção)
            </label>
          </div>
        )}

        <Button onClick={guardar} disabled={saving} className="w-full mt-2">
          {saving ? 'A guardar…' : (editar ? 'Guardar' : 'Criar unidade')}
        </Button>
      </DialogContent>
    </Dialog>
  );
}

export default function EstoqueUnidades() {
  const [unidades, setUnidades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoqueUnidades();
      setUnidades(r.data || []);
    } catch {
      toast.error('Não foi possível carregar as unidades.');
      setUnidades([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Unidades" subtitle="As lojas e fábricas de cada marca.">
        <Button onClick={() => setDialog({})}><Plus className="h-4 w-4 mr-1" /> Nova unidade</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : unidades.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Sem unidades.</p>
          ) : (
            <div className="divide-y">
              {unidades.map((u) => (
                <div
                  key={u.id}
                  className="p-4 flex items-center gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => setDialog({ unidade: u })}
                  role="button" tabIndex={0}
                >
                  <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center shrink-0">
                    {u.fabrica ? <Factory className="h-4 w-4 text-muted-foreground" /> : <Store className="h-4 w-4 text-muted-foreground" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{u.nome}</p>
                    <p className="text-xs text-muted-foreground">{marcaLabel(u.marca)}</p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {u.fabrica && <Badge variant="outline">fábrica</Badge>}
                    {!u.ativo && <Badge variant="secondary">inativa</Badge>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {dialog && <UnidadeDialog unidade={dialog.unidade} onClose={() => setDialog(null)} onSaved={load} />}
    </div>
  );
}
