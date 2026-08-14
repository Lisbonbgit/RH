import React, { useEffect, useState } from 'react';
import {
  getUtilizadores, criarUtilizador, editarUtilizador, mudarPin, mudarEstado, getLojas,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Switch } from '../../../components/ui/switch';
import { Checkbox } from '../../../components/ui/checkbox';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Users, Plus, Pencil, KeyRound } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const PERFIS = ['administrador', 'operador_caixa', 'contabilista'];
const PERFIL_LABELS = {
  administrador: 'Administrador',
  operador_caixa: 'Operador de caixa',
  contabilista: 'Contabilista',
};
const PERFIL_ESTILOS = {
  administrador: 'bg-purple-50 text-purple-700 border-purple-200',
  operador_caixa: 'bg-teal-50 text-teal-700 border-teal-200',
  contabilista: 'bg-amber-50 text-amber-700 border-amber-200',
};

const MSG_PIN_DIGITOS = 'O PIN tem de ter exactamente 4 dígitos.';
const MSG_PIN_REPETIDO = 'Já existe alguém nesta loja com esse PIN.';
const MSG_OPERADOR_SEM_LOJA = 'Um operador de caixa tem de ter pelo menos uma loja.';

const emptyForm = { nome: '', pin: '', perfil: '', lojas: [] };

// Só dígitos, no máximo 4 — preserva zeros à esquerda porque nunca passa por Number().
const soDigitos = (value) => value.replace(/\D/g, '').slice(0, 4);

// Traduz o erro do axios numa mensagem amigável e, quando o 422 aponta para
// um campo, devolve também o nome desse campo. Igual ao padrão dos outros
// ecrãs de Faturação (FatLojas, FatPagamentos, FatMotivos).
const detalhesErro = (error, fallback) => {
  const status = error.response?.status;
  const detail = error.response?.data?.detail;
  if (status === 422 && Array.isArray(detail) && detail.length > 0) {
    const primeiro = detail[0];
    const campo = Array.isArray(primeiro.loc) ? primeiro.loc[primeiro.loc.length - 1] : null;
    const mensagem = (primeiro.msg || '').replace(/^Value error,\s*/i, '') || fallback;
    return { campo, mensagem };
  }
  if (typeof detail === 'string' && detail) return { campo: null, mensagem: detail };
  return { campo: null, mensagem: fallback };
};

const perfilBadge = (perfil) => (
  <Badge variant="outline" className={PERFIL_ESTILOS[perfil] || 'bg-slate-100 text-slate-600 border-slate-200'}>
    {PERFIL_LABELS[perfil] || perfil}
  </Badge>
);

export default function FatUtilizadores() {
  const [utilizadores, setUtilizadores] = useState([]);
  const [lojas, setLojas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [togglingId, setTogglingId] = useState(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saving, setSaving] = useState(false);

  const [pinDialogOpen, setPinDialogOpen] = useState(false);
  const [pinTarget, setPinTarget] = useState(null);
  const [novoPin, setNovoPin] = useState('');
  const [pinError, setPinError] = useState('');
  const [savingPin, setSavingPin] = useState(false);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [u, l] = await Promise.all([getUtilizadores(), getLojas()]);
      setUtilizadores(u.data || []);
      setLojas(l.data || []);
    } catch (error) {
      toast.error('Erro ao carregar utilizadores');
    } finally {
      setLoading(false);
    }
  };

  const lojasPorId = Object.fromEntries(lojas.map((l) => [l.id, l]));

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm);
    setFieldErrors({});
    setDialogOpen(true);
  };

  const openEdit = (utilizador) => {
    setEditing(utilizador);
    setForm({
      nome: utilizador.nome || '',
      pin: '',
      perfil: utilizador.perfil || '',
      lojas: utilizador.lojas || [],
    });
    setFieldErrors({});
    setDialogOpen(true);
  };

  const toggleLoja = (id) => {
    setForm((prev) => ({
      ...prev,
      lojas: prev.lojas.includes(id) ? prev.lojas.filter((l) => l !== id) : [...prev.lojas, id],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.nome.trim()) { toast.error('Indique o nome do utilizador'); return; }
    if (!form.perfil) { toast.error('Escolha o perfil'); return; }
    if (form.perfil === 'operador_caixa' && form.lojas.length === 0) {
      toast.error(MSG_OPERADOR_SEM_LOJA);
      return;
    }
    if (!editing && form.pin.length !== 4) {
      setFieldErrors({ pin: MSG_PIN_DIGITOS });
      toast.error(MSG_PIN_DIGITOS);
      return;
    }
    const payload = {
      nome: form.nome.trim(),
      perfil: form.perfil,
      lojas: form.lojas,
    };
    if (!editing) payload.pin = form.pin;
    setSaving(true);
    setFieldErrors({});
    try {
      if (editing) { await editarUtilizador(editing.id, payload); toast.success('Utilizador atualizado'); }
      else { await criarUtilizador(payload); toast.success('Utilizador criado'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        const mensagem = error.response?.data?.detail || MSG_PIN_REPETIDO;
        setFieldErrors({ pin: mensagem });
        toast.error(mensagem);
        return;
      }
      if (status === 404) {
        toast.error('Este utilizador já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { campo, mensagem } = detalhesErro(error, 'Erro ao guardar o utilizador');
      if (campo) setFieldErrors({ [campo]: mensagem });
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const openMudarPin = (utilizador) => {
    setPinTarget(utilizador);
    setNovoPin('');
    setPinError('');
    setPinDialogOpen(true);
  };

  const handleSubmitPin = async (e) => {
    e.preventDefault();
    if (novoPin.length !== 4) {
      setPinError(MSG_PIN_DIGITOS);
      toast.error(MSG_PIN_DIGITOS);
      return;
    }
    setSavingPin(true);
    setPinError('');
    try {
      await mudarPin(pinTarget.id, novoPin);
      toast.success('PIN atualizado');
      setPinDialogOpen(false);
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        const mensagem = error.response?.data?.detail || MSG_PIN_REPETIDO;
        setPinError(mensagem);
        toast.error(mensagem);
        return;
      }
      if (status === 404) {
        toast.error('Este utilizador já não existe. A atualizar a lista...');
        setPinDialogOpen(false);
        fetchAll();
        return;
      }
      const { mensagem } = detalhesErro(error, 'Erro ao mudar o PIN');
      setPinError(mensagem);
      toast.error(mensagem);
    } finally {
      setSavingPin(false);
    }
  };

  // Nunca apaga — só ativa/desativa. O histórico de vendas aponta para o
  // utilizador, por isso o servidor nem tem endpoint de apagar.
  const handleToggleEstado = async (utilizador) => {
    const novoEstado = !(utilizador.ativo !== false);
    setTogglingId(utilizador.id);
    try {
      await mudarEstado(utilizador.id, novoEstado);
      toast.success(novoEstado ? 'Utilizador ativado' : 'Utilizador desativado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este utilizador já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao mudar o estado do utilizador');
      }
    } finally {
      setTogglingId(null);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-utilizadores-page">
      <PageHeader icon={Users} title="Utilizadores" subtitle="Quem entra no POS com PIN — nunca vê o backoffice">
        <Button onClick={openNew} data-testid="add-utilizador-btn"><Plus className="h-4 w-4 mr-2" />Novo utilizador</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : utilizadores.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Users className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem utilizadores</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie o primeiro utilizador para começar a vender no POS.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Perfil</TableHead>
                    <TableHead>Lojas</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {utilizadores.map((utilizador) => (
                    <TableRow key={utilizador.id} data-testid={`utilizador-row-${utilizador.id}`}>
                      <TableCell className="font-medium">{utilizador.nome}</TableCell>
                      <TableCell>{perfilBadge(utilizador.perfil)}</TableCell>
                      <TableCell>
                        {(utilizador.lojas || []).length === 0 ? (
                          <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">Todas as lojas</Badge>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {utilizador.lojas.map((id) => (
                              <Badge key={id} variant="outline" className="bg-slate-100 text-slate-700 border-slate-200">
                                {lojasPorId[id]?.nome || id}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Switch
                            checked={utilizador.ativo !== false}
                            onCheckedChange={() => handleToggleEstado(utilizador)}
                            disabled={togglingId === utilizador.id}
                            data-testid={`utilizador-estado-switch-${utilizador.id}`}
                          />
                          <span className="text-sm text-muted-foreground">
                            {utilizador.ativo !== false ? 'Ativo' : 'Inativo'}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button variant="ghost" size="icon" title="Mudar PIN" onClick={() => openMudarPin(utilizador)} data-testid={`mudar-pin-btn-${utilizador.id}`}>
                            <KeyRound className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" title="Editar" onClick={() => openEdit(utilizador)} data-testid={`edit-utilizador-${utilizador.id}`}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dialog criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="utilizador-dialog" className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar utilizador' : 'Novo utilizador'}</DialogTitle>
            <DialogDescription>
              Entra no POS tocando na sua foto e digitando o PIN — sem email nem palavra-passe.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="utilizador-nome">Nome *</Label>
                <Input
                  id="utilizador-nome"
                  value={form.nome}
                  onChange={(e) => setForm({ ...form, nome: e.target.value })}
                  placeholder="Ex: Rafaela Prates"
                  required
                  data-testid="utilizador-nome-input"
                />
              </div>

              {!editing && (
                <div className="space-y-2">
                  <Label htmlFor="utilizador-pin">PIN *</Label>
                  <Input
                    id="utilizador-pin"
                    type="password"
                    inputMode="numeric"
                    autoComplete="off"
                    value={form.pin}
                    onChange={(e) => {
                      setForm({ ...form, pin: soDigitos(e.target.value) });
                      setFieldErrors((prev) => ({ ...prev, pin: undefined }));
                    }}
                    placeholder="0000"
                    maxLength={4}
                    aria-invalid={!!fieldErrors.pin}
                    data-testid="utilizador-pin-input"
                  />
                  <p className="text-xs text-muted-foreground">
                    4 dígitos. Zeros à esquerda contam — "0007" é diferente de "7".
                  </p>
                  {fieldErrors.pin && (
                    <p className="text-xs text-destructive" data-testid="utilizador-pin-error">{fieldErrors.pin}</p>
                  )}
                </div>
              )}

              <div className="space-y-2">
                <Label>Perfil *</Label>
                <Select value={form.perfil} onValueChange={(v) => setForm({ ...form, perfil: v })}>
                  <SelectTrigger data-testid="utilizador-perfil-select"><SelectValue placeholder="Selecionar perfil" /></SelectTrigger>
                  <SelectContent>
                    {PERFIS.map((p) => (
                      <SelectItem key={p} value={p}>{PERFIL_LABELS[p]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Lojas</Label>
                <div className="flex flex-col gap-2 max-h-48 overflow-y-auto border rounded-md p-3" data-testid="utilizador-lojas-options">
                  {lojas.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Sem lojas criadas ainda.</p>
                  ) : (
                    lojas.map((loja) => (
                      <label key={loja.id} className="flex items-center gap-2 text-sm cursor-pointer" data-testid={`utilizador-loja-${loja.id}`}>
                        <Checkbox
                          checked={form.lojas.includes(loja.id)}
                          onCheckedChange={() => toggleLoja(loja.id)}
                          data-testid={`utilizador-loja-checkbox-${loja.id}`}
                        />
                        {loja.nome}
                      </label>
                    ))
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {form.perfil === 'operador_caixa'
                    ? 'Um operador de caixa tem de ter pelo menos uma loja.'
                    : 'Sem lojas selecionadas, o utilizador entra em qualquer loja.'}
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-utilizador-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Dialog mudar PIN */}
      <Dialog open={pinDialogOpen} onOpenChange={setPinDialogOpen}>
        <DialogContent data-testid="pin-dialog">
          <DialogHeader>
            <DialogTitle>Mudar PIN</DialogTitle>
            <DialogDescription>{pinTarget ? `Utilizador: ${pinTarget.nome}` : ''}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmitPin}>
            <div className="space-y-2 py-4">
              <Label htmlFor="novo-pin">PIN novo *</Label>
              <Input
                id="novo-pin"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                value={novoPin}
                onChange={(e) => { setNovoPin(soDigitos(e.target.value)); setPinError(''); }}
                placeholder="0000"
                maxLength={4}
                aria-invalid={!!pinError}
                data-testid="novo-pin-input"
              />
              <p className="text-xs text-muted-foreground">4 dígitos. Zeros à esquerda contam.</p>
              {pinError && <p className="text-xs text-destructive" data-testid="pin-error">{pinError}</p>}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setPinDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={savingPin} data-testid="save-pin-btn">{savingPin ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
