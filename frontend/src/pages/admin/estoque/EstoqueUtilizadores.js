import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  getEstoqueUtilizadores, criarEstoqueUtilizador, editarEstoqueUtilizador, apagarEstoqueUtilizador, getEstoqueUnidades,
} from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../components/ui/dialog';
import { Users, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCAS = [['lacai', "L'açaí"], ['lenha_brasa', 'Lenha e Brasa'], ['purple', 'Purple House']];
const soDigitos = (v) => String(v || '').replace(/[^0-9]/g, '');

// Cria colaboradores (login + PIN + lojas) e edita colaboradores/administradores.
// Os ADMINISTRADORES entram por email+senha (convite), um fluxo que se gere na
// app do estoque — aqui só se ajusta o nome e o estado (ativo).
function UserDialog({ user, unidades, onClose, onSaved, onDelete }) {
  const editar = !!user;
  const ehAdmin = editar && user.papel === 'admin';
  const marcaDe = (ids) => unidades.find((u) => (ids || []).includes(u.id))?.marca || 'lacai';

  const [nome, setNome] = useState(user?.nome || '');
  const [username, setUsername] = useState(user?.username || '');
  const [pin, setPin] = useState('');
  const [marca, setMarca] = useState(user ? marcaDe(user.unidade_ids) : 'lacai');
  const [lojaIds, setLojaIds] = useState(user?.unidade_ids || []);
  const [ativo, setAtivo] = useState(user ? user.ativo : true);
  const [saving, setSaving] = useState(false);

  const lojasDaMarca = useMemo(() => unidades.filter((u) => u.marca === marca), [unidades, marca]);
  const toggleLoja = (id) => setLojaIds((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  // Ao trocar de marca, larga as lojas que já não são dessa marca.
  useEffect(() => { setLojaIds((s) => s.filter((id) => lojasDaMarca.some((u) => u.id === id))); }, [marca]); // eslint-disable-line

  async function guardar() {
    if (!nome.trim()) return toast.error('Indica o nome.');
    let body;
    if (ehAdmin) {
      // Administrador: só nome + estado (o email/senha gere-se na app do estoque).
      body = { nome: nome.trim(), ativo };
    } else {
      if (!username.trim()) return toast.error('Indica o nome de utilizador (login).');
      body = { nome: nome.trim(), username: username.trim(), unidade_ids: lojaIds };
      if (lojaIds.length === 0) return toast.error('Escolhe pelo menos uma loja.');
      if (!editar && !/^\d{4,}$/.test(pin)) return toast.error('O PIN tem de ter pelo menos 4 dígitos.');
      if (pin) {
        if (!/^\d{4,}$/.test(pin)) return toast.error('O PIN tem de ter pelo menos 4 dígitos.');
        body.pin = pin;
      }
      if (editar) body.ativo = ativo;
    }

    setSaving(true);
    try {
      if (editar) {
        await editarEstoqueUtilizador(user.id, body);
        toast.success('Utilizador atualizado.');
      } else {
        await criarEstoqueUtilizador(body);
        toast.success('Colaborador criado.');
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
      <DialogContent className="sm:max-w-md max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editar ? (ehAdmin ? 'Administrador' : 'Editar colaborador') : 'Novo colaborador'}</DialogTitle>
          <DialogDescription>
            {ehAdmin ? 'Entra por email e senha (gerido na app do estoque). Aqui ajustas o nome e o estado.'
              : editar ? user.nome : 'Um login de colaborador (nome de utilizador + PIN).'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label>Nome</Label>
          <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: Beatrice Brito" />
        </div>

        {ehAdmin ? (
          <>
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input value={user.email || ''} disabled />
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={ativo} onChange={(e) => setAtivo(e.target.checked)} className="h-4 w-4" />
              Ativo
            </label>
          </>
        ) : (
          <>
            <div className="space-y-1.5">
              <Label>Nome de utilizador (login)</Label>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="ex.: beatrice.b" />
            </div>
            <div className="space-y-1.5">
              <Label>Marca</Label>
              <Select value={marca} onValueChange={setMarca}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{MARCAS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Lojas</Label>
              <div className="rounded-lg border p-2 space-y-1.5 max-h-40 overflow-y-auto">
                {lojasDaMarca.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Sem lojas nesta marca.</p>
                ) : lojasDaMarca.map((u) => (
                  <label key={u.id} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="checkbox" checked={lojaIds.includes(u.id)} onChange={() => toggleLoja(u.id)} className="h-4 w-4" />
                    {u.nome}{!u.ativo ? ' (inativa)' : ''}
                  </label>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>{editar ? 'Repor PIN (opcional)' : 'PIN (4+ dígitos)'}</Label>
              <Input inputMode="numeric" value={pin} onChange={(e) => setPin(soDigitos(e.target.value))} placeholder={editar ? 'deixa vazio para não mudar' : 'ex.: 1234'} maxLength={8} />
            </div>
            {editar && (
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={ativo} onChange={(e) => setAtivo(e.target.checked)} className="h-4 w-4" />
                Ativo
              </label>
            )}
          </>
        )}

        <Button onClick={guardar} disabled={saving} className="w-full mt-2">
          {saving ? 'A guardar…' : (editar ? 'Guardar alterações' : 'Criar colaborador')}
        </Button>
        {editar && (
          <Button type="button" variant="ghost" className="w-full text-destructive" disabled={saving} onClick={onDelete}>
            <Trash2 className="h-4 w-4 mr-1" /> Apagar utilizador
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function EstoqueUtilizadores() {
  const [users, setUsers] = useState([]);
  const [unidades, setUnidades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(null);

  const nomeLoja = useMemo(() => {
    const m = {}; unidades.forEach((u) => { m[u.id] = u.nome; }); return m;
  }, [unidades]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [u, un] = await Promise.all([getEstoqueUtilizadores(), getEstoqueUnidades()]);
      setUsers(u.data || []);
      setUnidades(un.data || []);
    } catch {
      toast.error('Não foi possível carregar os utilizadores.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function apagar(u) {
    if (!window.confirm(`Apagar o utilizador "${u.nome}"? O histórico dele fica, mas perde o acesso.`)) return;
    try {
      await apagarEstoqueUtilizador(u.id);
      toast.success('Utilizador apagado.');
      setDialog(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível apagar.');
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Utilizadores" subtitle="Os logins do estoque. Cria e gere colaboradores (login + PIN + lojas).">
        <Button onClick={() => setDialog({})}><Plus className="h-4 w-4 mr-1" /> Novo colaborador</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : users.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">Sem utilizadores.</p>
          ) : (
            <div className="divide-y">
              {users.map((u) => (
                <div
                  key={u.id}
                  className="p-4 flex items-center gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => setDialog({ user: u })}
                  role="button" tabIndex={0}
                >
                  <div className="h-9 w-9 rounded-full bg-muted flex items-center justify-center shrink-0">
                    <Users className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {u.nome} <span className="text-xs text-muted-foreground font-normal">· {u.username || u.email}</span>
                    </p>
                    <p className="text-xs text-muted-foreground truncate">
                      {u.papel === 'admin' ? 'Administrador' : (u.unidade_ids || []).map((id) => nomeLoja[id] || '?').join(', ') || 'sem loja'}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {u.papel === 'admin' && <Badge variant="outline">admin</Badge>}
                    {!u.ativo && <Badge variant="secondary">inativo</Badge>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {dialog && (
        <UserDialog
          user={dialog.user}
          unidades={unidades}
          onClose={() => setDialog(null)}
          onSaved={load}
          onDelete={() => apagar(dialog.user)}
        />
      )}
    </div>
  );
}
