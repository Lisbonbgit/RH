import React, { useEffect, useState } from 'react';
import {
  getTiposPagamento, getCodigosFiscais, criarTipoPagamento, editarTipoPagamento, apagarTipoPagamento,
  detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Switch } from '../../../components/ui/switch';
import { RadioGroup, RadioGroupItem } from '../../../components/ui/radio-group';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { CreditCard, Plus, Pencil, Trash2, Lock, Banknote } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const emptyForm = { nome: '', tipo_fiscal: '', da_troco: null, ordem: '0', ativo: true };

const AVISO_PROTEGIDO = "Este tipo de pagamento é usado pela app L'Açaí e não pode ser alterado nem apagado aqui.";

const estadoBadge = (ativo) => (
  ativo !== false
    ? <Badge variant="outline" className="bg-teal-50 text-teal-700 border-teal-200">Ativo</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Inativo</Badge>
);

const trocoBadge = (daTroco) => (
  daTroco
    ? <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 gap-1"><Banknote className="h-3 w-3" />Dá troco</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Não dá troco</Badge>
);

export default function FatPagamentos() {
  const [tipos, setTipos] = useState([]);
  const [codigosFiscais, setCodigosFiscais] = useState({});
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [t, c] = await Promise.all([getTiposPagamento(), getCodigosFiscais()]);
      setTipos(t.data || []);
      setCodigosFiscais(c.data || {});
    } catch (error) {
      toast.error('Erro ao carregar tipos de pagamento');
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm);
    setFieldErrors({});
    setDialogOpen(true);
  };

  // O ecrã não deixa sequer tentar editar um tipo protegido (o servidor
  // devolve 409, mas o botão de editar nem chega a abrir o formulário).
  const openEdit = (tipo) => {
    if (tipo.protegido) {
      toast.info(AVISO_PROTEGIDO);
      return;
    }
    setEditing(tipo);
    setForm({
      nome: tipo.nome || '',
      tipo_fiscal: tipo.tipo_fiscal || '',
      da_troco: tipo.da_troco === true,
      ordem: String(tipo.ordem ?? 0),
      ativo: tipo.ativo !== false,
    });
    setFieldErrors({});
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.nome.trim()) { toast.error('Indique o nome do tipo de pagamento'); return; }
    if (!form.tipo_fiscal) { toast.error('Escolha o código fiscal'); return; }
    if (form.da_troco === null) { toast.error("Escolha se este tipo de pagamento dá troco"); return; }
    const payload = {
      nome: form.nome.trim(),
      tipo_fiscal: form.tipo_fiscal,
      da_troco: form.da_troco,
      ordem: parseInt(form.ordem, 10) || 0,
      ativo: form.ativo,
    };
    // O PUT do servidor substitui o registo inteiro. vendus_payment_method_id
    // não tem campo neste formulário — sem o reenviar aqui, gravar o tipo de
    // pagamento punha-o a null e cortava, em silêncio, a ligação ao Vendus.
    if (editing) payload.vendus_payment_method_id = editing.vendus_payment_method_id ?? null;
    setSaving(true);
    setFieldErrors({});
    try {
      if (editing) { await editarTipoPagamento(editing.id, payload); toast.success('Tipo de pagamento atualizado'); }
      else { await criarTipoPagamento(payload); toast.success('Tipo de pagamento criado'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || AVISO_PROTEGIDO);
        setDialogOpen(false);
        fetchAll();
        return;
      }
      if (status === 404) {
        toast.error('Este tipo de pagamento já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { campo, mensagem } = detalhesErro(error, 'Erro ao guardar o tipo de pagamento');
      if (campo) setFieldErrors({ [campo]: mensagem });
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const askDelete = (tipo) => {
    if (tipo.protegido) {
      toast.info(AVISO_PROTEGIDO);
      return;
    }
    setDeleteTarget(tipo);
  };

  const handleDelete = async () => {
    const alvo = deleteTarget;
    setDeleteTarget(null);
    try {
      await apagarTipoPagamento(alvo.id);
      toast.success('Tipo de pagamento eliminado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || AVISO_PROTEGIDO);
        fetchAll();
      } else if (status === 404) {
        toast.error('Este tipo de pagamento já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar o tipo de pagamento');
      }
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-pagamentos-page">
      <PageHeader icon={CreditCard} title="Tipos de Pagamento" subtitle="Meios de pagamento aceites e os seus códigos fiscais">
        <Button onClick={openNew} data-testid="add-pagamento-btn"><Plus className="h-4 w-4 mr-2" />Novo tipo</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : tipos.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CreditCard className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem tipos de pagamento</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie o primeiro tipo para começar a faturar.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Título</TableHead>
                    <TableHead>Troco</TableHead>
                    <TableHead>Tipo fiscal</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tipos.map((tipo) => (
                    <TableRow key={tipo.id} data-testid={`pagamento-row-${tipo.id}`}>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          {tipo.nome}
                          {tipo.protegido && (
                            <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-label="Protegido" />
                          )}
                        </div>
                      </TableCell>
                      <TableCell>{trocoBadge(tipo.da_troco)}</TableCell>
                      <TableCell>
                        <span className="text-sm text-muted-foreground">
                          {codigosFiscais[tipo.tipo_fiscal] || tipo.tipo_fiscal}
                        </span>
                      </TableCell>
                      <TableCell>{estadoBadge(tipo.ativo)}</TableCell>
                      <TableCell className="text-right">
                        {tipo.protegido ? (
                          <div className="flex items-center justify-end">
                            <Button
                              variant="ghost"
                              size="icon"
                              title={AVISO_PROTEGIDO}
                              onClick={() => toast.info(AVISO_PROTEGIDO)}
                              data-testid={`locked-pagamento-${tipo.id}`}
                            >
                              <Lock className="h-4 w-4 text-muted-foreground" />
                            </Button>
                          </div>
                        ) : (
                          <div className="flex items-center justify-end gap-2">
                            <Button variant="ghost" size="icon" onClick={() => openEdit(tipo)} data-testid={`edit-pagamento-${tipo.id}`}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="icon" onClick={() => askDelete(tipo)} data-testid={`delete-pagamento-${tipo.id}`}>
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        )}
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
        <DialogContent data-testid="pagamento-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar tipo de pagamento' : 'Novo tipo de pagamento'}</DialogTitle>
            <DialogDescription>O nome é livre; o código fiscal é o que vai para o documento emitido no Vendus.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="pagamento-nome">Nome *</Label>
                <Input
                  id="pagamento-nome"
                  value={form.nome}
                  onChange={(e) => setForm({ ...form, nome: e.target.value })}
                  placeholder="Ex: Glovo"
                  required
                  maxLength={60}
                  data-testid="pagamento-nome-input"
                />
                {fieldErrors.nome && <p className="text-xs text-destructive">{fieldErrors.nome}</p>}
              </div>
              <div className="space-y-2">
                <Label>Código fiscal *</Label>
                <Select value={form.tipo_fiscal} onValueChange={(v) => setForm({ ...form, tipo_fiscal: v })}>
                  <SelectTrigger data-testid="pagamento-tipo-fiscal-select"><SelectValue placeholder="Selecionar código fiscal" /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(codigosFiscais).map(([codigo, label]) => (
                      <SelectItem key={codigo} value={codigo}>{codigo} — {label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">É como este tipo é reportado ao fisco, independentemente do nome mostrado no balcão.</p>
              </div>
              <div className="space-y-2">
                <Label>Dá troco? *</Label>
                <RadioGroup
                  value={form.da_troco === null ? undefined : (form.da_troco ? 'sim' : 'nao')}
                  onValueChange={(v) => setForm({ ...form, da_troco: v === 'sim' })}
                  className="flex items-center gap-6"
                  data-testid="pagamento-da-troco-radio"
                >
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="sim" id="da-troco-sim" />
                    <Label htmlFor="da-troco-sim" className="cursor-pointer font-normal">Sim</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="nao" id="da-troco-nao" />
                    <Label htmlFor="da-troco-nao" className="cursor-pointer font-normal">Não</Label>
                  </div>
                </RadioGroup>
                <p className="text-xs text-muted-foreground">Só faz sentido em dinheiro. Marcar "Sim" num pagamento eletrónico faz o POS pedir troco por engano no balcão.</p>
              </div>
              <div className="grid grid-cols-2 gap-4 items-end">
                <div className="space-y-2">
                  <Label htmlFor="pagamento-ordem">Ordem</Label>
                  <Input
                    id="pagamento-ordem"
                    type="number"
                    value={form.ordem}
                    onChange={(e) => setForm({ ...form, ordem: e.target.value })}
                    data-testid="pagamento-ordem-input"
                  />
                </div>
                <div className="flex items-center gap-2 pb-2.5">
                  <Switch id="pagamento-ativo" checked={form.ativo} onCheckedChange={(v) => setForm({ ...form, ativo: v })} data-testid="pagamento-ativo-switch" />
                  <Label htmlFor="pagamento-ativo" className="cursor-pointer">Ativo</Label>
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-pagamento-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar tipo de pagamento</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.nome}"? Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
