import React, { useState, useEffect, useCallback } from 'react';
import { getEstoquePessoas, criarEstoquePessoa, editarEstoquePessoa } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../components/ui/dialog';
import { UserRound, Plus } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const soDigitos = (v) => String(v || '').replace(/[^0-9]/g, '');

function PessoaDialog({ pessoa, onClose, onSaved }) {
  const editar = !!pessoa;
  const [nome, setNome] = useState(pessoa?.nome || '');
  const [codigo, setCodigo] = useState('');
  const [ativo, setAtivo] = useState(pessoa ? pessoa.ativo : true);
  const [podeTransferir, setPodeTransferir] = useState(pessoa?.pode_transferir || false);
  const [saving, setSaving] = useState(false);

  async function guardar() {
    if (!nome.trim()) return toast.error('Indica o nome.');
    if (!editar && !/^\d{4,6}$/.test(codigo)) return toast.error('O código tem de ter 4 a 6 dígitos.');
    setSaving(true);
    try {
      if (editar) {
        const body = { nome: nome.trim(), ativo, pode_transferir: podeTransferir };
        if (codigo) {
          if (!/^\d{4,6}$/.test(codigo)) { setSaving(false); return toast.error('O novo código tem de ter 4 a 6 dígitos.'); }
          body.codigo = codigo;
        }
        await editarEstoquePessoa(pessoa.id, body);
        toast.success('Pessoa atualizada.');
      } else {
        await criarEstoquePessoa({ nome: nome.trim(), codigo });
        toast.success('Pessoa criada.');
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
          <DialogTitle>{editar ? 'Editar pessoa' : 'Nova pessoa'}</DialogTitle>
          <DialogDescription>
            {editar ? pessoa.nome : 'O código pessoal serve para identificar quem faz cada alteração no telemóvel.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label>Nome</Label>
          <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: Beatrice" />
        </div>

        <div className="space-y-1.5">
          <Label>{editar ? 'Repor código (opcional)' : 'Código (4 a 6 dígitos)'}</Label>
          <Input
            inputMode="numeric"
            value={codigo}
            onChange={(e) => setCodigo(soDigitos(e.target.value))}
            placeholder={editar ? 'deixa vazio para não mudar' : 'ex.: 1234'}
            maxLength={6}
          />
          {editar && <p className="text-[11px] text-muted-foreground">A pessoa troca-o no 1.º uso. O código atual nunca é mostrado.</p>}
        </div>

        {editar && (
          <div className="space-y-2 pt-1">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={ativo} onChange={(e) => setAtivo(e.target.checked)} className="h-4 w-4" />
              Ativa
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={podeTransferir} onChange={(e) => setPodeTransferir(e.target.checked)} className="h-4 w-4" />
              Pode iniciar transferências entre lojas
            </label>
          </div>
        )}

        <Button onClick={guardar} disabled={saving} className="w-full mt-2">
          {saving ? 'A guardar…' : (editar ? 'Guardar' : 'Criar pessoa')}
        </Button>
      </DialogContent>
    </Dialog>
  );
}

export default function EstoquePessoas() {
  const [pessoas, setPessoas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoquePessoas();
      setPessoas(r.data || []);
    } catch {
      toast.error('Não foi possível carregar as pessoas.');
      setPessoas([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Pessoas" subtitle="Quem está — códigos pessoais que registam quem faz cada alteração.">
        <Button onClick={() => setDialog({})}><Plus className="h-4 w-4 mr-1" /> Nova pessoa</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : pessoas.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Ainda não há pessoas.</p>
          ) : (
            <div className="divide-y">
              {pessoas.map((p) => (
                <div
                  key={p.id}
                  className="p-4 flex items-center gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => setDialog({ pessoa: p })}
                  role="button" tabIndex={0}
                >
                  <div className="h-9 w-9 rounded-full bg-muted flex items-center justify-center shrink-0">
                    <UserRound className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{p.nome}</p>
                    <p className="text-xs text-muted-foreground">
                      {p.must_change_codigo ? 'código temporário (troca no 1.º uso)' : 'código definido'}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {p.pode_transferir && <Badge variant="outline">transfere</Badge>}
                    {!p.ativo && <Badge variant="secondary">inativa</Badge>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {dialog && <PessoaDialog pessoa={dialog.pessoa} onClose={() => setDialog(null)} onSaved={load} />}
    </div>
  );
}
