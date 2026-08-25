import React, { useEffect, useState } from 'react';
import {
  getCategorias, criarCategoria, editarCategoria, apagarCategoria,
  getSubcategorias, criarSubcategoria, editarSubcategoria, apagarSubcategoria,
  detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Switch } from '../../../components/ui/switch';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Tag, Plus, Pencil, Trash2, FolderTree, Loader2 } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const NOME_MAX = 80;
const emptyForm = { nome: '', ordem: '0', ativa: true };

const estadoBadge = (ativa) => (
  ativa !== false
    ? <Badge variant="outline" className="bg-teal-50 text-teal-700 border-teal-200">Ativa</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Inativa</Badge>
);

// **As subcategorias de UMA categoria** — «dentro do Venda ao Público quero
// criar uma subcategoria», nas palavras do dono. Vivem aqui, no ecrã das
// categorias, e não num ecrã à parte: é dentro da categoria que se pensa
// nelas.
//
// São só arrumação da grelha do POS. Não entram na fatura, no IVA nem nos
// relatórios — e a importação do Vendus não lhes toca (o Vendus não tem este
// nível). O que ela reescreve é a CATEGORIA do produto, que continua a ser
// dela; por isso um produto que mude de categoria lá perde a subcategoria, e a
// importação diz qual foi.
function DialogoSubcategorias({ categoria, onFechar }) {
  const [subcategorias, setSubcategorias] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [nome, setNome] = useState('');
  const [aGravar, setAGravar] = useState(false);

  const recarregar = React.useCallback(async () => {
    if (!categoria) return;
    setCarregando(true);
    try {
      const { data } = await getSubcategorias(categoria.id);
      setSubcategorias(data || []);
    } catch (error) {
      toast.error('Erro ao carregar as subcategorias');
    } finally {
      setCarregando(false);
    }
  }, [categoria]);

  useEffect(() => { recarregar(); }, [recarregar]);

  const acrescentar = async (e) => {
    e.preventDefault();
    const limpo = nome.trim();
    if (!limpo || aGravar) return;
    setAGravar(true);
    try {
      // A ordem nasce no fim da lista: quem cria uma subcategoria nova está a
      // acrescentar ao que já lá está, não a pôr à frente de tudo.
      await criarSubcategoria({
        nome: limpo, categoria_id: categoria.id, ordem: subcategorias.length, ativa: true,
      });
      setNome('');
      await recarregar();
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível criar a subcategoria.').mensagem);
    } finally {
      setAGravar(false);
    }
  };

  const renomear = async (sub, novoNome) => {
    const limpo = (novoNome || '').trim();
    if (!limpo || limpo === sub.nome) return;
    try {
      await editarSubcategoria(sub.id, {
        nome: limpo, categoria_id: sub.categoria_id, ordem: sub.ordem ?? 0,
        ativa: sub.ativa !== false,
      });
      await recarregar();
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível renomear.').mensagem);
      await recarregar();
    }
  };

  const apagar = async (sub) => {
    try {
      const { data } = await apagarSubcategoria(sub.id);
      // Apagar NÃO apaga produtos: eles ficam sem subcategoria e continuam na
      // grelha, em "Outros". Dizê-lo aqui evita o susto de quem carregou.
      const soltos = data?.produtos_soltos || 0;
      toast.success(soltos
        ? `Subcategoria apagada. ${soltos} produto(s) ficaram sem subcategoria — continuam à venda.`
        : 'Subcategoria apagada.');
      await recarregar();
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível apagar.').mensagem);
    }
  };

  return (
    <Dialog open={!!categoria} onOpenChange={(aberto) => { if (!aberto) onFechar(); }}>
      <DialogContent data-testid="subcategorias-dialog">
        <DialogHeader>
          <DialogTitle>Subcategorias de "{categoria?.nome}"</DialogTitle>
          <DialogDescription>
            Arrumam a grelha do POS dentro deste separador. Um produto pode ficar sem
            subcategoria — aparece na mesma, em "Outros".
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {carregando ? (
            <div className="flex items-center justify-center h-20">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : subcategorias.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              Ainda não há subcategorias aqui. Enquanto não houver, a grelha do POS fica
              exactamente como está hoje.
            </p>
          ) : (
            <div className="rounded-xl border divide-y">
              {subcategorias.map((sub) => (
                <div key={sub.id} className="flex items-center gap-2 p-2">
                  <Input
                    defaultValue={sub.nome}
                    maxLength={NOME_MAX}
                    onBlur={(e) => renomear(sub, e.target.value)}
                    data-testid={`subcategoria-nome-${sub.id}`}
                  />
                  <Button
                    type="button" variant="ghost" size="icon"
                    onClick={() => apagar(sub)}
                    aria-label={`Apagar ${sub.nome}`}
                    data-testid={`apagar-subcategoria-${sub.id}`}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          <form onSubmit={acrescentar} className="flex items-center gap-2">
            <Input
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Nova subcategoria (ex: Açaís)"
              maxLength={NOME_MAX}
              data-testid="nova-subcategoria-input"
            />
            <Button type="submit" disabled={!nome.trim() || aGravar} data-testid="criar-subcategoria-btn">
              <Plus className="h-4 w-4 mr-1" /> Criar
            </Button>
          </form>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onFechar}>Fechar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


export default function FatCategorias() {
  const [categorias, setCategorias] = useState([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [subcategoriasDe, setSubcategoriasDe] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const { data } = await getCategorias();
      setCategorias(data || []);
    } catch (error) {
      toast.error('Erro ao carregar categorias');
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => { setEditing(null); setForm(emptyForm); setFieldErrors({}); setDialogOpen(true); };
  const openEdit = (categoria) => {
    setEditing(categoria);
    setForm({
      nome: categoria.nome || '',
      ordem: String(categoria.ordem ?? 0),
      ativa: categoria.ativa !== false,
    });
    setFieldErrors({});
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nome = form.nome.trim();
    if (!nome) { toast.error('Indique o nome da categoria'); return; }
    if (nome.length > NOME_MAX) { toast.error(`O nome não pode ter mais de ${NOME_MAX} caracteres`); return; }
    const payload = {
      nome,
      ordem: parseInt(form.ordem, 10) || 0,
      ativa: form.ativa,
    };
    setSaving(true);
    setFieldErrors({});
    try {
      if (editing) { await editarCategoria(editing.id, payload); toast.success('Categoria atualizada'); }
      else { await criarCategoria(payload); toast.success('Categoria criada'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Esta categoria já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { campo, mensagem } = detalhesErro(error, 'Erro ao guardar a categoria');
      if (campo) setFieldErrors({ [campo]: mensagem });
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const alvo = deleteTarget;
    setDeleteTarget(null);
    try {
      await apagarCategoria(alvo.id);
      toast.success('Categoria eliminada');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || 'Esta categoria ainda tem produtos. Mude-os de categoria primeiro.');
      } else if (status === 404) {
        toast.error('Esta categoria já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar a categoria');
      }
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-categorias-page">
      <PageHeader
        icon={Tag}
        title="Categorias"
        subtitle="Venda ao Público e Vendas Aplicações — cada produto pertence a uma"
      >
        <Button onClick={openNew} data-testid="add-categoria-btn"><Plus className="h-4 w-4 mr-2" />Nova categoria</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : categorias.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Tag className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem categorias</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie a categoria "Venda ao Público" para começar, ou importe do Vendus.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Ordem</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {categorias.map((categoria) => (
                    <TableRow key={categoria.id} data-testid={`categoria-row-${categoria.id}`}>
                      <TableCell className="font-medium">{categoria.nome}</TableCell>
                      <TableCell className="text-muted-foreground">{categoria.ordem ?? 0}</TableCell>
                      <TableCell>{estadoBadge(categoria.ativa)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="outline"
                            onClick={() => setSubcategoriasDe(categoria)}
                            data-testid={`subcategorias-categoria-${categoria.id}`}
                          >
                            <FolderTree className="h-4 w-4 mr-1.5" />
                            Subcategorias
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => openEdit(categoria)} data-testid={`edit-categoria-${categoria.id}`}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(categoria)} data-testid={`delete-categoria-${categoria.id}`}>
                            <Trash2 className="h-4 w-4 text-destructive" />
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

      <DialogoSubcategorias
        categoria={subcategoriasDe}
        onFechar={() => setSubcategoriasDe(null)}
      />

      {/* Dialog criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="categoria-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar categoria' : 'Nova categoria'}</DialogTitle>
            <DialogDescription>Cada produto pertence a uma só categoria, com o seu próprio preço.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="categoria-nome">Nome *</Label>
                <Input
                  id="categoria-nome"
                  value={form.nome}
                  onChange={(e) => { setForm({ ...form, nome: e.target.value }); setFieldErrors((prev) => ({ ...prev, nome: undefined })); }}
                  placeholder="Ex: Venda ao Público"
                  required
                  maxLength={NOME_MAX}
                  aria-invalid={!!fieldErrors.nome}
                  data-testid="categoria-nome-input"
                />
                {fieldErrors.nome && <p className="text-xs text-destructive">{fieldErrors.nome}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="categoria-ordem">Ordem</Label>
                <Input
                  id="categoria-ordem"
                  type="number"
                  value={form.ordem}
                  onChange={(e) => setForm({ ...form, ordem: e.target.value })}
                  data-testid="categoria-ordem-input"
                />
                <p className="text-xs text-muted-foreground">Ordem de aparição no POS. Menor primeiro.</p>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Switch id="categoria-ativa" checked={form.ativa} onCheckedChange={(v) => setForm({ ...form, ativa: v })} data-testid="categoria-ativa-switch" />
                <Label htmlFor="categoria-ativa" className="cursor-pointer">Categoria ativa</Label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-categoria-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar categoria</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.nome}"? Esta ação não pode ser desfeita. Só é possível eliminar categorias sem produtos.
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
