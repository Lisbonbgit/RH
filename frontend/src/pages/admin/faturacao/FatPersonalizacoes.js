import React, { useEffect, useState } from 'react';
import {
  getGrupos, criarGrupo, editarGrupo, apagarGrupo,
  detalhesErro, temMaisDe2CasasDecimais,
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
import { Sparkles, Plus, Pencil, Trash2, X } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const NOME_GRUPO_MAX = 80;
const NOME_OPCAO_MAX = 60;

const emptyOpcao = () => ({ id: null, nome: '', preco: '0', ativa: true });
const emptyForm = {
  nome: '', min_select: '0', max_select: '0', ativo: true, opcoes: [],
  // Mesmos defaults do servidor (catalogo.py): "opcoes" e sai_na_fatura=true —
  // um grupo novo abre já como os toppings de sempre, não como o Nome/Levar.
  tipo: 'opcoes', sai_na_fatura: true,
};

// Semântica DERIVADA (faturacao/catalogo.py): sem campos "obrigatorio" ou
// "tipo" no servidor — só min_select/max_select. Mostra-se por palavras aqui,
// nunca os números crus, mas os únicos campos enviados ao servidor continuam
// a ser min_select/max_select.
const regrasDoGrupo = (minSelect, maxSelect) => {
  const min = Number(minSelect) || 0;
  const max = Number(maxSelect) || 0;
  const obrigatorio = min >= 1;
  let escolha;
  if (max === 1) escolha = 'Escolha única';
  else if (max === 0) escolha = 'Sem limite';
  else escolha = `Até ${max} escolhas`;
  return { obrigatorio, escolha };
};

const fmtEUR = (n) => new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(Number(n) || 0);

export default function FatPersonalizacoes() {
  const [grupos, setGrupos] = useState([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState('');
  const [opcaoErrors, setOpcaoErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const { data } = await getGrupos();
      setGrupos(data || []);
    } catch (error) {
      toast.error('Erro ao carregar personalizações');
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm);
    setFormError('');
    setOpcaoErrors({});
    setDialogOpen(true);
  };

  const openEdit = (grupo) => {
    setEditing(grupo);
    setForm({
      nome: grupo.nome || '',
      min_select: String(grupo.min_select ?? 0),
      max_select: String(grupo.max_select ?? 0),
      ativo: grupo.ativo !== false,
      tipo: grupo.tipo || 'opcoes',
      sai_na_fatura: grupo.sai_na_fatura !== false,
      opcoes: (grupo.opcoes || []).map((o) => ({
        id: o.id || null,
        nome: o.nome || '',
        preco: String(o.preco ?? 0),
        ativa: o.ativa !== false,
      })),
    });
    setFormError('');
    setOpcaoErrors({});
    setDialogOpen(true);
  };

  const addOpcao = () => setForm((prev) => ({ ...prev, opcoes: [...prev.opcoes, emptyOpcao()] }));
  const removeOpcao = (index) => {
    setForm((prev) => ({ ...prev, opcoes: prev.opcoes.filter((_, i) => i !== index) }));
    setOpcaoErrors((prev) => { const next = { ...prev }; delete next[index]; return next; });
  };
  const updateOpcao = (index, patch) => {
    setForm((prev) => ({
      ...prev,
      opcoes: prev.opcoes.map((o, i) => (i === index ? { ...o, ...patch } : o)),
    }));
    setOpcaoErrors((prev) => ({ ...prev, [index]: undefined }));
  };

  const changeTipo = (tipo) => {
    setForm((prev) => ({
      ...prev,
      tipo,
      // "um grupo de texto não tem opções" (catalogo.py) — limpa-as ao mudar
      // para Texto livre, senão opções de uma escolha anterior seguiam
      // penduradas no payload sem aparecerem no ecrã (fantasmas no servidor).
      opcoes: tipo === 'texto' ? [] : prev.opcoes,
    }));
    setOpcaoErrors({});
    setFormError('');
  };

  const validar = () => {
    const nome = form.nome.trim();
    if (!nome) { toast.error('Indique o nome do grupo'); return false; }
    if (nome.length > NOME_GRUPO_MAX) { toast.error(`O nome não pode ter mais de ${NOME_GRUPO_MAX} caracteres`); return false; }

    const min = parseInt(form.min_select, 10) || 0;
    const max = parseInt(form.max_select, 10) || 0;
    if (min < 0 || max < 0) { setFormError('O mínimo e o máximo de escolhas não podem ser negativos'); return false; }
    // Mesma guarda condicional do model_validator do servidor (catalogo.py):
    // um grupo de texto não tem opções, e comparar min_select com
    // len(opcoes) recusava sempre um Nome marcado como obrigatório.
    if (form.tipo === 'opcoes') {
      if (max > 0 && min > max) {
        setFormError('O mínimo de escolhas não pode ser maior do que o máximo');
        return false;
      }
      if (min > form.opcoes.length) {
        setFormError('O mínimo de escolhas não pode ser maior do que o número de opções do grupo');
        return false;
      }
    }
    setFormError('');

    const erros = {};
    form.opcoes.forEach((opcao, i) => {
      const linhaErros = {};
      if (!opcao.nome.trim()) linhaErros.nome = 'Indique o nome da opção';
      else if (opcao.nome.trim().length > NOME_OPCAO_MAX) linhaErros.nome = `Máximo de ${NOME_OPCAO_MAX} caracteres`;
      const preco = Number(opcao.preco);
      if (opcao.preco === '' || !Number.isFinite(preco)) linhaErros.preco = 'Indique um preço válido';
      else if (preco < 0) linhaErros.preco = 'O preço não pode ser negativo';
      else if (temMaisDe2CasasDecimais(opcao.preco)) linhaErros.preco = 'Máximo de 2 casas decimais';
      if (Object.keys(linhaErros).length > 0) erros[i] = linhaErros;
    });
    setOpcaoErrors(erros);
    if (Object.keys(erros).length > 0) { toast.error('Há opções com dados inválidos'); return false; }

    return true;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validar()) return;
    const payload = {
      nome: form.nome.trim(),
      min_select: parseInt(form.min_select, 10) || 0,
      max_select: parseInt(form.max_select, 10) || 0,
      ativo: form.ativo,
      tipo: form.tipo,
      sai_na_fatura: form.sai_na_fatura,
      opcoes: form.opcoes.map((o) => ({
        id: o.id || undefined,
        nome: o.nome.trim(),
        preco: Number(o.preco) || 0,
        ativa: o.ativa,
      })),
    };
    setSaving(true);
    try {
      if (editing) { await editarGrupo(editing.id, payload); toast.success('Grupo de personalização atualizado'); }
      else { await criarGrupo(payload); toast.success('Grupo de personalização criado'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este grupo já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { mensagem } = detalhesErro(error, 'Erro ao guardar o grupo de personalização');
      setFormError(mensagem);
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const alvo = deleteTarget;
    setDeleteTarget(null);
    try {
      await apagarGrupo(alvo.id);
      toast.success('Grupo de personalização eliminado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || 'Este grupo ainda está atribuído a produtos. Retire-o dos produtos primeiro.');
      } else if (status === 404) {
        toast.error('Este grupo já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar o grupo de personalização');
      }
    }
  };

  const previaRegras = regrasDoGrupo(form.min_select, form.max_select);

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-personalizacoes-page">
      <PageHeader
        icon={Sparkles}
        title="Personalizações"
        subtitle="Grupos de toppings — depois atribuem-se aos produtos"
      >
        <Button onClick={openNew} data-testid="add-grupo-btn"><Plus className="h-4 w-4 mr-2" />Novo grupo</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : grupos.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Sparkles className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem grupos de personalização</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie o primeiro grupo — por exemplo "Toppings" — e depois atribua-o aos produtos.</p>
            </div>
          ) : (
            <div className="divide-y">
              {grupos.map((grupo) => {
                const { obrigatorio, escolha } = regrasDoGrupo(grupo.min_select, grupo.max_select);
                const opcoes = grupo.opcoes || [];
                return (
                  <div key={grupo.id} className="p-4" data-testid={`grupo-row-${grupo.id}`}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="font-semibold">{grupo.nome}</h3>
                          {grupo.ativo === false && (
                            <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Inativo</Badge>
                          )}
                          <Badge variant="outline" className={obrigatorio ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-slate-100 text-slate-600 border-slate-200'}>
                            {obrigatorio ? 'Obrigatório' : 'Opcional'}
                          </Badge>
                          <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">{escolha}</Badge>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {opcoes.length === 0 ? (
                            <span className="text-sm text-muted-foreground">Sem opções ainda.</span>
                          ) : (
                            opcoes.map((o) => (
                              <Badge key={o.id || o.nome} variant="secondary" className={o.ativa === false ? 'opacity-50' : ''}>
                                {o.nome} · {fmtEUR(o.preco)}
                              </Badge>
                            ))
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Button variant="ghost" size="icon" onClick={() => openEdit(grupo)} data-testid={`edit-grupo-${grupo.id}`}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(grupo)} data-testid={`delete-grupo-${grupo.id}`}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dialog criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="grupo-dialog" className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar grupo de personalização' : 'Novo grupo de personalização'}</DialogTitle>
            <DialogDescription>Ex.: "Toppings" com as opções Banana, Granola e Oreo grátis, e Nutella, Mel e Whey a pagar.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="grupo-nome">Nome *</Label>
                <Input
                  id="grupo-nome"
                  value={form.nome}
                  onChange={(e) => setForm({ ...form, nome: e.target.value })}
                  placeholder="Ex: Toppings"
                  required
                  maxLength={NOME_GRUPO_MAX}
                  data-testid="grupo-nome-input"
                />
              </div>

              <div className="space-y-2">
                <Label>Tipo *</Label>
                <RadioGroup
                  value={form.tipo}
                  onValueChange={changeTipo}
                  className="flex items-center gap-6"
                  data-testid="grupo-tipo-radio"
                >
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="opcoes" id="grupo-tipo-opcoes" />
                    <Label htmlFor="grupo-tipo-opcoes" className="cursor-pointer font-normal">Lista de opções</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <RadioGroupItem value="texto" id="grupo-tipo-texto" />
                    <Label htmlFor="grupo-tipo-texto" className="cursor-pointer font-normal">Texto livre</Label>
                  </div>
                </RadioGroup>
                <p className="text-xs text-muted-foreground">
                  Lista de opções — ao balcão, a funcionária escolhe entre alternativas já definidas (ex.: toppings).
                </p>
                <p className="text-xs text-muted-foreground">
                  Texto livre — ao balcão, a funcionária escreve uma resposta (ex.: o nome no copo).
                </p>
              </div>

              {form.tipo === 'opcoes' ? (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="grupo-min">Mínimo de escolhas</Label>
                      <Input
                        id="grupo-min"
                        type="number"
                        min="0"
                        value={form.min_select}
                        onChange={(e) => { setForm({ ...form, min_select: e.target.value }); setFormError(''); }}
                        data-testid="grupo-min-input"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="grupo-max">Máximo de escolhas</Label>
                      <Input
                        id="grupo-max"
                        type="number"
                        min="0"
                        value={form.max_select}
                        onChange={(e) => { setForm({ ...form, max_select: e.target.value }); setFormError(''); }}
                        data-testid="grupo-max-input"
                      />
                      <p className="text-xs text-muted-foreground">0 = sem limite</p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                    <span className="text-muted-foreground">Isto torna o grupo:</span>
                    <Badge variant="outline" className={previaRegras.obrigatorio ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-slate-100 text-slate-600 border-slate-200'}>
                      {previaRegras.obrigatorio ? 'Obrigatório' : 'Opcional'}
                    </Badge>
                    <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">{previaRegras.escolha}</Badge>
                  </div>
                </>
              ) : (
                <div className="flex items-center gap-2">
                  <Switch
                    id="grupo-obrigatorio"
                    checked={Number(form.min_select) >= 1}
                    onCheckedChange={(v) => { setForm({ ...form, min_select: v ? '1' : '0' }); setFormError(''); }}
                    data-testid="grupo-obrigatorio-switch"
                  />
                  <Label htmlFor="grupo-obrigatorio" className="cursor-pointer">Resposta obrigatória</Label>
                </div>
              )}
              {formError && <p className="text-xs text-destructive" data-testid="grupo-form-error">{formError}</p>}

              <div className="flex items-center gap-2">
                <Switch id="grupo-ativo" checked={form.ativo} onCheckedChange={(v) => setForm({ ...form, ativo: v })} data-testid="grupo-ativo-switch" />
                <Label htmlFor="grupo-ativo" className="cursor-pointer">Grupo ativo</Label>
              </div>

              <div className="space-y-1.5 rounded-md border px-3 py-3">
                <div className="flex items-center gap-2">
                  <Switch
                    id="grupo-sai-na-fatura"
                    checked={form.sai_na_fatura}
                    onCheckedChange={(v) => setForm({ ...form, sai_na_fatura: v })}
                    data-testid="grupo-sai-na-fatura-switch"
                  />
                  <Label htmlFor="grupo-sai-na-fatura" className="cursor-pointer">Sai na fatura</Label>
                </div>
                <p className="text-xs text-muted-foreground">
                  As escolhas deste grupo aparecem na fatura do cliente. Desligue num grupo que seja só
                  para a cozinha — o nome no copo, ou levar/comer aqui.
                </p>
                <p className="text-xs text-muted-foreground">Uma opção paga aparece sempre, mesmo com isto desligado.</p>
              </div>

              {form.tipo === 'opcoes' && (
              <div className="space-y-2 pt-2 border-t">
                <div className="flex items-center justify-between pt-3">
                  <Label>Opções</Label>
                  <Button type="button" variant="outline" size="sm" onClick={addOpcao} data-testid="add-opcao-btn">
                    <Plus className="h-3.5 w-3.5 mr-1.5" />Adicionar opção
                  </Button>
                </div>
                {form.opcoes.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Sem opções. Adicione a primeira — ex.: "Banana", €0,00.</p>
                ) : (
                  <div className="space-y-2">
                    {form.opcoes.map((opcao, index) => (
                      <div key={index} className="flex items-start gap-2" data-testid={`opcao-row-${index}`}>
                        <div className="flex-1 space-y-1">
                          <Input
                            value={opcao.nome}
                            onChange={(e) => updateOpcao(index, { nome: e.target.value })}
                            placeholder="Nome da opção"
                            maxLength={NOME_OPCAO_MAX}
                            aria-invalid={!!opcaoErrors[index]?.nome}
                            data-testid={`opcao-nome-input-${index}`}
                          />
                          {opcaoErrors[index]?.nome && <p className="text-xs text-destructive">{opcaoErrors[index].nome}</p>}
                        </div>
                        <div className="w-28 space-y-1">
                          <Input
                            type="number"
                            step="0.01"
                            min="0"
                            value={opcao.preco}
                            onChange={(e) => updateOpcao(index, { preco: e.target.value })}
                            placeholder="0.00"
                            aria-invalid={!!opcaoErrors[index]?.preco}
                            data-testid={`opcao-preco-input-${index}`}
                          />
                          {opcaoErrors[index]?.preco && <p className="text-xs text-destructive">{opcaoErrors[index].preco}</p>}
                        </div>
                        <div className="flex items-center h-10 gap-2 shrink-0">
                          <Switch
                            checked={opcao.ativa}
                            onCheckedChange={(v) => updateOpcao(index, { ativa: v })}
                            title="Opção ativa"
                            data-testid={`opcao-ativa-switch-${index}`}
                          />
                          <Button type="button" variant="ghost" size="icon" onClick={() => removeOpcao(index)} data-testid={`remove-opcao-${index}`}>
                            <X className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-grupo-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar grupo de personalização</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.nome}"? Esta ação não pode ser desfeita. Só é possível eliminar grupos que não estejam atribuídos a produtos.
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
