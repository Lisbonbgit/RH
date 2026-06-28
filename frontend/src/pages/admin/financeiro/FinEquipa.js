import React, { useState, useEffect } from 'react';
import {
  getFinTeam, addFinTeamMember, updateFinTeamMember, removeFinTeamMember,
} from '../../../lib/api';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Card, CardContent } from '../../../components/ui/card';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Users, UserPlus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

// Papéis que se podem atribuir à equipa (o 'owner' não se atribui por aqui).
const ASSIGNABLE_ROLES = [
  { value: 'partner', label: 'Sócio', hint: 'Pode ver e editar' },
  { value: 'accountant', label: 'Contabilista', hint: 'Só leitura' },
];
const ROLE_LABEL = { owner: 'Dono', partner: 'Sócio', accountant: 'Contabilista' };

export default function FinEquipa() {
  const [team, setTeam] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ email: '', role: 'partner' });
  const [saving, setSaving] = useState(false);
  const [memberToRemove, setMemberToRemove] = useState(null);

  useEffect(() => { fetchTeam(); }, []);

  const fetchTeam = async () => {
    setLoading(true);
    try {
      const res = await getFinTeam();
      setTeam(res.data);
    } catch (error) {
      toast.error('Erro ao carregar equipa');
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await addFinTeamMember(form);
      toast.success('Membro adicionado à equipa');
      setAddOpen(false);
      setForm({ email: '', role: 'partner' });
      fetchTeam();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao adicionar membro');
    } finally {
      setSaving(false);
    }
  };

  const handleChangeRole = async (member, role) => {
    try {
      await updateFinTeamMember(member.member_id, role);
      setTeam((prev) => prev.map((m) => (m.member_id === member.member_id ? { ...m, role } : m)));
      toast.success('Papel atualizado');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao atualizar papel');
      fetchTeam();
    }
  };

  const handleRemove = async () => {
    try {
      await removeFinTeamMember(memberToRemove.member_id);
      toast.success('Membro removido');
      setMemberToRemove(null);
      fetchTeam();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao remover membro');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-equipa-page">
      <PageHeader icon={Users} title="Equipa" subtitle="Quem adicionares tem acesso a todas as tuas empresas">
        <Button onClick={() => setAddOpen(true)} data-testid="fin-add-member-btn">
          <UserPlus className="h-4 w-4 mr-2" />
          Adicionar Membro
        </Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : team.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Users className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem membros na equipa</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Adiciona pessoas (que já tenham conta) para partilharem o acesso às tuas empresas.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Membro</TableHead>
                    <TableHead className="hidden sm:table-cell">Email</TableHead>
                    <TableHead>Papel</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {team.map((m) => (
                    <TableRow key={m.member_id} data-testid={`fin-member-row-${m.member_id}`}>
                      <TableCell className="font-medium">{m.name || m.email}</TableCell>
                      <TableCell className="hidden sm:table-cell text-muted-foreground">{m.email}</TableCell>
                      <TableCell>
                        <Select value={m.role} onValueChange={(v) => handleChangeRole(m, v)}>
                          <SelectTrigger className="w-40" data-testid={`fin-member-role-${m.member_id}`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {ASSIGNABLE_ROLES.map((r) => (
                              <SelectItem key={r.value} value={r.value}>
                                {r.label} — <span className="text-muted-foreground">{r.hint}</span>
                              </SelectItem>
                            ))}
                            {m.role === 'owner' && <SelectItem value="owner">Dono</SelectItem>}
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon" onClick={() => setMemberToRemove(m)}
                          data-testid={`fin-remove-member-${m.member_id}`}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dialog adicionar membro */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent data-testid="fin-add-member-dialog">
          <DialogHeader>
            <DialogTitle>Adicionar Membro</DialogTitle>
            <DialogDescription>
              A pessoa tem de já ter conta no sistema. Fica com acesso a todas as tuas empresas (atuais e futuras).
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleAdd}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="fin-member-email">Email *</Label>
                <Input id="fin-member-email" type="email" value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="pessoa@exemplo.com" required data-testid="fin-member-email-input" />
              </div>
              <div className="space-y-2">
                <Label>Papel</Label>
                <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                  <SelectTrigger data-testid="fin-member-role-select">
                    <SelectValue placeholder="Selecione o papel" />
                  </SelectTrigger>
                  <SelectContent>
                    {ASSIGNABLE_ROLES.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label} — <span className="text-muted-foreground">{r.hint}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="fin-save-member-btn">
                {saving ? 'A adicionar...' : 'Adicionar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar remover */}
      <AlertDialog open={!!memberToRemove} onOpenChange={(o) => !o && setMemberToRemove(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remover Membro</AlertDialogTitle>
            <AlertDialogDescription>
              Remover "{memberToRemove?.name || memberToRemove?.email}" da equipa? Perde o acesso a todas as tuas empresas.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleRemove} className="bg-destructive text-destructive-foreground"
              data-testid="fin-confirm-remove-member-btn">
              Remover
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
