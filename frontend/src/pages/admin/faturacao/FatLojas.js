import React, { useEffect, useState } from 'react';
import {
  getLojas, criarLoja, editarLoja, apagarLoja,
  getCaixas, criarCaixa, editarCaixa, apagarCaixa,
  getSincronizacaoApp, guardarSincronizacaoApp, sincronizarAppAgora,
  resumoDaSincronizacao, detalhesErro,
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
import {
  Store, Plus, Pencil, Trash2, Wallet, MapPin, Mail, Phone, Smartphone,
  RefreshCw,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const CP_REGEX = /^\d{4}-\d{3}$/;

const emptyLojaForm = {
  nome: '', morada: '', codigo_postal: '', localidade: '', email: '', telefone: '', cae: '', ativa: true,
};
const emptyCaixaForm = { nome: '', ativa: true };

// Vai inserindo o hífen à medida que o utilizador escreve (0000-000).
const formatCodigoPostal = (value) => {
  const digitos = value.replace(/\D/g, '').slice(0, 7);
  if (digitos.length <= 4) return digitos;
  return `${digitos.slice(0, 4)}-${digitos.slice(4)}`;
};

const moradaCompleta = (loja) => {
  const linha2 = [loja.codigo_postal, loja.localidade].filter(Boolean).join(' ');
  return [loja.morada, linha2].filter(Boolean).join(', ');
};

const estadoBadge = (ativa) => (
  ativa !== false
    ? <Badge variant="outline" className="bg-teal-50 text-teal-700 border-teal-200">Ativa</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Inativa</Badge>
);

export default function FatLojas() {
  const [lojas, setLojas] = useState([]);
  const [caixasPorLoja, setCaixasPorLoja] = useState({});
  const [loading, setLoading] = useState(true);

  const [lojaDialogOpen, setLojaDialogOpen] = useState(false);
  const [editingLoja, setEditingLoja] = useState(null);
  const [lojaForm, setLojaForm] = useState(emptyLojaForm);
  const [lojaFieldErrors, setLojaFieldErrors] = useState({});
  const [savingLoja, setSavingLoja] = useState(false);
  const [deleteLojaTarget, setDeleteLojaTarget] = useState(null);

  // A loja que recebe as vendas da app L'Açaí — `{ loja_id, ativo }` em
  // `fat_definicoes` (faturacao/sincronizacao_rota.py). Fica `{}` enquanto
  // ninguém a escolher, e nesse estado a sincronização não corre de todo.
  const [sincApp, setSincApp] = useState({});
  const [aGuardarApp, setAGuardarApp] = useState(false);
  const [aSincronizarApp, setASincronizarApp] = useState(false);

  const [caixaDialogOpen, setCaixaDialogOpen] = useState(false);
  const [caixaLoja, setCaixaLoja] = useState(null);
  const [editingCaixa, setEditingCaixa] = useState(null);
  const [caixaForm, setCaixaForm] = useState(emptyCaixaForm);
  const [savingCaixa, setSavingCaixa] = useState(false);
  const [deleteCaixaTarget, setDeleteCaixaTarget] = useState(null);

  useEffect(() => { fetchAll(); carregarSincApp(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const { data } = await getLojas();
      const listaLojas = data || [];
      setLojas(listaLojas);
      // allSettled: uma loja cujas caixas falhem a carregar (sessão expirada,
      // blip de rede) não pode apagar as caixas das restantes lojas, que já
      // vieram bem. Mostra-se o que se conseguiu ler e avisa-se do que faltou.
      const resultados = await Promise.allSettled(listaLojas.map((l) => getCaixas(l.id)));
      const mapa = {};
      let falhas = 0;
      listaLojas.forEach((l, i) => {
        const resultado = resultados[i];
        if (resultado.status === 'fulfilled') {
          mapa[l.id] = resultado.value.data || [];
        } else {
          falhas += 1;
        }
      });
      setCaixasPorLoja(mapa);
      if (falhas > 0) {
        toast.error(
          falhas === 1
            ? 'Não foi possível carregar as caixas de uma loja. Verifique antes de criar caixas novas.'
            : `Não foi possível carregar as caixas de ${falhas} lojas. Verifique antes de criar caixas novas.`
        );
      }
    } catch (error) {
      toast.error('Erro ao carregar lojas');
    } finally {
      setLoading(false);
    }
  };

  // --- As vendas da app L'Açaí ---
  //
  // A app emite as Faturas Simplificadas dela pela MESMA caixa API e pela MESMA
  // série das lojas. O portal vai buscá-las ao Vendus de 5 em 5 minutos e
  // grava-as na loja escolhida aqui; sem loja escolhida não corre de todo, e
  // diz porquê — adivinhá-la era pôr a receita da app na loja errada.

  const carregarSincApp = async () => {
    try {
      const { data } = await getSincronizacaoApp();
      setSincApp(data || {});
    } catch (error) {
      // Em silêncio, a etiqueta apagada lia-se como "ninguém escolheu loja
      // nenhuma" — que é o estado em que a app não é faturada em lado nenhum.
      toast.error(detalhesErro(
        error, 'Não foi possível saber que loja recebe as vendas da app.').mensagem);
    }
  };

  const escolherLojaDaApp = async (loja) => {
    setAGuardarApp(true);
    // **O `ativo` que já lá estava vai com a loja.** O PUT grava o modelo
    // inteiro (`$set` de `sincronizacao_rota.py`), e um `ativo: true` fixo
    // RELIGAVA em silêncio uma sincronização que alguém tinha desligado de
    // propósito — bastava trocar de loja. Trocar a loja é trocar a loja.
    const ativo = sincApp.ativo !== false;
    try {
      const { data } = await guardarSincronizacaoApp({ loja_id: loja.id, ativo });
      setSincApp(data || {});
      toast.success(ativo
        ? `As vendas da app passam a entrar em ${loja.nome}.`
        : `${loja.nome} passa a ser a loja das vendas da app — mas a `
          + 'sincronização continua desligada.');
    } catch (error) {
      toast.error(detalhesErro(
        error, 'Não foi possível guardar a loja das vendas da app.').mensagem);
    } finally {
      setAGuardarApp(false);
    }
  };

  // Ligar e desligar a sincronização da loja escolhida. Sem isto, «Vendas da
  // app (desligada)» era um estado que o ecrã sabia mostrar e não sabia nem
  // produzir nem repor: quem a desligasse (ou a apanhasse desligada) ficava
  // sem caminho de volta que não fosse a base de dados.
  const ligarSincApp = async (ativo) => {
    setAGuardarApp(true);
    try {
      const { data } = await guardarSincronizacaoApp({
        loja_id: sincApp.loja_id, ativo });
      setSincApp(data || {});
      toast.success(ativo
        ? 'As vendas da app voltam a entrar sozinhas, de 5 em 5 minutos.'
        : 'Sincronização desligada: as faturas da app deixam de entrar no '
          + 'portal — continuam a ser emitidas no Vendus.');
    } catch (error) {
      toast.error(detalhesErro(
        error, 'Não foi possível mudar a sincronização das vendas da app.').mensagem);
    } finally {
      setAGuardarApp(false);
    }
  };

  const sincronizarApp = async () => {
    setASincronizarApp(true);
    try {
      const { data } = await sincronizarAppAgora();
      const resumo = resumoDaSincronizacao(data);
      // Os `assinalados` são documentos que ficaram de fora POR AVARIA e que
      // não voltam a ser tentados (a janela do cron só olha para hoje e ontem).
      // Quem carregou no botão é quem pode agir — por isso ficam mais tempo no
      // ecrã, e em linhas separadas.
      toast[resumo.tipo](resumo.titulo, {
        description: <span className="whitespace-pre-line">{resumo.descricao}</span>,
        duration: resumo.tipo === 'success' ? 6000 : 15000,
      });
    } catch (error) {
      toast.error(detalhesErro(
        error,
        'A sincronização não chegou ao fim — o Vendus pode estar lento. O que '
        + 'faltar entra sozinho na próxima volta.').mensagem);
    } finally {
      setASincronizarApp(false);
    }
  };

  const refreshCaixas = async (lojaId) => {
    try {
      const { data } = await getCaixas(lojaId);
      setCaixasPorLoja((prev) => ({ ...prev, [lojaId]: data || [] }));
    } catch (error) {
      toast.error('Não foi possível atualizar a lista de caixas desta loja. Atualize a página para confirmar se a operação foi guardada.');
    }
  };

  // --- Loja ---

  const openNewLoja = () => {
    setEditingLoja(null);
    setLojaForm(emptyLojaForm);
    setLojaFieldErrors({});
    setLojaDialogOpen(true);
  };

  const openEditLoja = (loja) => {
    setEditingLoja(loja);
    setLojaForm({
      nome: loja.nome || '',
      morada: loja.morada || '',
      codigo_postal: loja.codigo_postal || '',
      localidade: loja.localidade || '',
      email: loja.email || '',
      telefone: loja.telefone || '',
      cae: loja.cae || '',
      ativa: loja.ativa !== false,
    });
    setLojaFieldErrors({});
    setLojaDialogOpen(true);
  };

  const handleSubmitLoja = async (e) => {
    e.preventDefault();
    if (!lojaForm.nome.trim()) { toast.error('Indique o nome da loja'); return; }
    if (lojaForm.codigo_postal && !CP_REGEX.test(lojaForm.codigo_postal)) {
      setLojaFieldErrors({ codigo_postal: 'Código postal tem de ser no formato 0000-000' });
      return;
    }
    const payload = {
      nome: lojaForm.nome.trim(),
      morada: lojaForm.morada.trim() || null,
      codigo_postal: lojaForm.codigo_postal.trim() || null,
      localidade: lojaForm.localidade.trim() || null,
      email: lojaForm.email.trim() || null,
      telefone: lojaForm.telefone.trim() || null,
      cae: lojaForm.cae.trim() || null,
      ativa: lojaForm.ativa,
    };
    // O PUT do servidor substitui o registo inteiro (não é um PATCH parcial).
    // empresa_id e rh_location_id não têm campo neste formulário — sem os
    // reenviar aqui, gravar a loja punha-os a null e cortava, em silêncio,
    // a ligação à empresa/loja do RH.
    if (editingLoja) {
      payload.empresa_id = editingLoja.empresa_id ?? null;
      payload.rh_location_id = editingLoja.rh_location_id ?? null;
    }
    setSavingLoja(true);
    setLojaFieldErrors({});
    try {
      if (editingLoja) { await editarLoja(editingLoja.id, payload); toast.success('Loja atualizada'); }
      else { await criarLoja(payload); toast.success('Loja criada'); }
      setLojaDialogOpen(false);
      fetchAll();
    } catch (error) {
      if (error.response?.status === 404) {
        toast.error('Esta loja já não existe. A atualizar a lista...');
        setLojaDialogOpen(false);
        fetchAll();
        return;
      }
      const { campo, mensagem } = detalhesErro(error, 'Erro ao guardar a loja');
      if (campo) setLojaFieldErrors({ [campo]: mensagem });
      toast.error(mensagem);
    } finally {
      setSavingLoja(false);
    }
  };

  const handleDeleteLoja = async () => {
    const alvo = deleteLojaTarget;
    setDeleteLojaTarget(null);
    try {
      await apagarLoja(alvo.id);
      toast.success('Loja eliminada');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || 'Esta loja ainda tem caixas. Apague-as primeiro.');
      } else if (status === 404) {
        toast.error('Esta loja já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar a loja');
      }
    }
  };

  // --- Caixa ---

  const openNewCaixa = (loja) => {
    setCaixaLoja(loja);
    setEditingCaixa(null);
    setCaixaForm(emptyCaixaForm);
    setCaixaDialogOpen(true);
  };

  const openEditCaixa = (loja, caixa) => {
    setCaixaLoja(loja);
    setEditingCaixa(caixa);
    setCaixaForm({ nome: caixa.nome || '', ativa: caixa.ativa !== false });
    setCaixaDialogOpen(true);
  };

  const handleSubmitCaixa = async (e) => {
    e.preventDefault();
    if (!caixaForm.nome.trim()) { toast.error('Indique o nome da caixa'); return; }
    const payload = { nome: caixaForm.nome.trim(), ativa: caixaForm.ativa };
    setSavingCaixa(true);
    try {
      if (editingCaixa) { await editarCaixa(editingCaixa.id, payload); toast.success('Caixa atualizada'); }
      else { await criarCaixa(caixaLoja.id, payload); toast.success('Caixa criada'); }
      setCaixaDialogOpen(false);
      refreshCaixas(caixaLoja.id);
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este registo já não existe. A atualizar a lista...');
        setCaixaDialogOpen(false);
        fetchAll();
      } else {
        const { mensagem } = detalhesErro(error, 'Erro ao guardar a caixa');
        toast.error(mensagem);
      }
    } finally {
      setSavingCaixa(false);
    }
  };

  const handleDeleteCaixa = async () => {
    const alvo = deleteCaixaTarget;
    setDeleteCaixaTarget(null);
    try {
      await apagarCaixa(alvo.caixa.id);
      toast.success('Caixa eliminada');
      refreshCaixas(alvo.loja.id);
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Esta caixa já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar a caixa');
      }
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-lojas-page">
      <PageHeader icon={Store} title="Lojas e Caixas" subtitle="Lojas de faturação e as caixas de cada uma">
        <Button onClick={openNewLoja} data-testid="add-loja-btn"><Plus className="h-4 w-4 mr-2" />Nova loja</Button>
      </PageHeader>

      {loading ? (
        <div className="flex items-center justify-center h-32">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
        </div>
      ) : lojas.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Store className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="font-medium text-lg">Sem lojas</h3>
            <p className="text-sm text-muted-foreground mt-1">Crie a primeira loja para começar a faturar.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {lojas.map((loja) => {
            const caixas = caixasPorLoja[loja.id] || [];
            const morada = moradaCompleta(loja);
            return (
              <Card key={loja.id} data-testid={`loja-card-${loja.id}`}>
                <CardContent className="p-0">
                  <div className="flex flex-wrap items-start justify-between gap-3 p-4 border-b">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-lg">{loja.nome}</h3>
                        {estadoBadge(loja.ativa)}
                        {/* As faturas que a app L'Açaí emite entram nesta loja.
                            `ativo: false` é a sincronização desligada — a
                            etiqueta tem de o dizer, senão promete uma receita
                            que não está a entrar em lado nenhum. */}
                        {sincApp.loja_id === loja.id && (
                          <Badge
                            variant="outline"
                            className="bg-violet-50 text-violet-700 border-violet-200"
                            data-testid={`loja-app-badge-${loja.id}`}
                          >
                            <Smartphone className="h-3 w-3 mr-1" />
                            {sincApp.ativo === false
                              ? 'Vendas da app (desligada)'
                              : 'Vendas da app'}
                          </Badge>
                        )}
                      </div>
                      <div className="text-sm text-muted-foreground mt-1 space-y-0.5">
                        {morada && (
                          <div className="flex items-center gap-1.5">
                            <MapPin className="h-3.5 w-3.5 shrink-0" />
                            <span>{morada}</span>
                          </div>
                        )}
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5">
                          {loja.cae && <span>CAE {loja.cae}</span>}
                          {loja.email && (
                            <span className="flex items-center gap-1"><Mail className="h-3.5 w-3.5" />{loja.email}</span>
                          )}
                          {loja.telefone && (
                            <span className="flex items-center gap-1"><Phone className="h-3.5 w-3.5" />{loja.telefone}</span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {sincApp.loja_id === loja.id ? (
                        <>
                          {/* O interruptor da sincronização desta loja. A
                              etiqueta «(desligada)» lá em cima já mostrava o
                              estado; isto é o que o produz e o repõe. */}
                          <div className="flex items-center gap-2 mr-1">
                            <Switch
                              checked={sincApp.ativo !== false}
                              onCheckedChange={ligarSincApp}
                              disabled={aGuardarApp}
                              aria-label="Sincronização das vendas da app"
                              title="Desligue para parar de trazer as faturas da app para o portal"
                              data-testid={`sinc-app-ativo-${loja.id}`}
                            />
                            <span className="text-sm text-muted-foreground">Sincronização</span>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={sincronizarApp}
                            disabled={aSincronizarApp || sincApp.ativo === false}
                            title={sincApp.ativo === false
                              ? 'A sincronização está desligada — ligue-a para poder trazer as faturas'
                              : 'Vai ao Vendus buscar as faturas de hoje e de ontem que a app emitiu'}
                            data-testid={`sincronizar-app-${loja.id}`}
                          >
                            <RefreshCw className={`h-4 w-4 mr-1.5 ${aSincronizarApp ? 'animate-spin' : ''}`} />
                            Sincronizar agora
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => escolherLojaDaApp(loja)}
                          disabled={aGuardarApp}
                          title="As Faturas Simplificadas que a app L'Açaí emite passam a ser gravadas nesta loja"
                          data-testid={`escolher-app-${loja.id}`}
                        >
                          <Smartphone className="h-4 w-4 mr-1.5" />
                          Receber vendas da app
                        </Button>
                      )}
                      <Button variant="outline" size="sm" onClick={() => openNewCaixa(loja)} data-testid={`add-caixa-btn-${loja.id}`}>
                        <Plus className="h-4 w-4 mr-1.5" />Nova caixa
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => openEditLoja(loja)} data-testid={`edit-loja-${loja.id}`}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => setDeleteLojaTarget(loja)} data-testid={`delete-loja-${loja.id}`}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                  <div className="p-4">
                    {caixas.length === 0 ? (
                      <p className="text-sm text-muted-foreground">Sem caixas. Adicione uma para começar a faturar nesta loja.</p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Caixa</TableHead>
                            <TableHead>Estado</TableHead>
                            <TableHead className="text-right">Ações</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {caixas.map((caixa) => (
                            <TableRow key={caixa.id} data-testid={`caixa-row-${caixa.id}`}>
                              <TableCell className="font-medium">
                                <div className="flex items-center gap-2">
                                  <Wallet className="h-4 w-4 text-muted-foreground" />
                                  {caixa.nome}
                                </div>
                              </TableCell>
                              <TableCell>{estadoBadge(caixa.ativa)}</TableCell>
                              <TableCell className="text-right">
                                <div className="flex items-center justify-end gap-2">
                                  <Button variant="ghost" size="icon" onClick={() => openEditCaixa(loja, caixa)} data-testid={`edit-caixa-${caixa.id}`}>
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                  <Button variant="ghost" size="icon" onClick={() => setDeleteCaixaTarget({ loja, caixa })} data-testid={`delete-caixa-${caixa.id}`}>
                                    <Trash2 className="h-4 w-4 text-destructive" />
                                  </Button>
                                </div>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Dialog criar/editar loja */}
      <Dialog open={lojaDialogOpen} onOpenChange={setLojaDialogOpen}>
        <DialogContent data-testid="loja-dialog" className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingLoja ? 'Editar loja' : 'Nova loja'}</DialogTitle>
            <DialogDescription>A morada e o CAE aparecem no cabeçalho das faturas emitidas nesta loja.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmitLoja}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="loja-nome">Nome *</Label>
                <Input
                  id="loja-nome"
                  value={lojaForm.nome}
                  onChange={(e) => setLojaForm({ ...lojaForm, nome: e.target.value })}
                  placeholder="Ex: Açaí Algueirão"
                  required
                  maxLength={120}
                  data-testid="loja-nome-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="loja-morada">Morada</Label>
                <Input
                  id="loja-morada"
                  value={lojaForm.morada}
                  onChange={(e) => setLojaForm({ ...lojaForm, morada: e.target.value })}
                  placeholder="Rua, número"
                  data-testid="loja-morada-input"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="loja-cp">Código postal</Label>
                  <Input
                    id="loja-cp"
                    value={lojaForm.codigo_postal}
                    onChange={(e) => {
                      setLojaForm({ ...lojaForm, codigo_postal: formatCodigoPostal(e.target.value) });
                      setLojaFieldErrors((prev) => ({ ...prev, codigo_postal: undefined }));
                    }}
                    placeholder="0000-000"
                    maxLength={8}
                    aria-invalid={!!lojaFieldErrors.codigo_postal}
                    data-testid="loja-cp-input"
                  />
                  {lojaFieldErrors.codigo_postal && (
                    <p className="text-xs text-destructive" data-testid="loja-cp-error">{lojaFieldErrors.codigo_postal}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="loja-localidade">Localidade</Label>
                  <Input
                    id="loja-localidade"
                    value={lojaForm.localidade}
                    onChange={(e) => setLojaForm({ ...lojaForm, localidade: e.target.value })}
                    placeholder="Ex: Sintra"
                    data-testid="loja-localidade-input"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="loja-email">Email</Label>
                  <Input
                    id="loja-email"
                    type="email"
                    value={lojaForm.email}
                    onChange={(e) => setLojaForm({ ...lojaForm, email: e.target.value })}
                    placeholder="loja@exemplo.pt"
                    data-testid="loja-email-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="loja-telefone">Telefone</Label>
                  <Input
                    id="loja-telefone"
                    value={lojaForm.telefone}
                    onChange={(e) => setLojaForm({ ...lojaForm, telefone: e.target.value })}
                    placeholder="912 345 678"
                    data-testid="loja-telefone-input"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="loja-cae">CAE</Label>
                <Input
                  id="loja-cae"
                  value={lojaForm.cae}
                  onChange={(e) => setLojaForm({ ...lojaForm, cae: e.target.value })}
                  placeholder="Ex: 56104"
                  data-testid="loja-cae-input"
                />
                <p className="text-xs text-muted-foreground">Código de Atividade Económica, usado nos documentos fiscais emitidos nesta loja.</p>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Switch id="loja-ativa" checked={lojaForm.ativa} onCheckedChange={(v) => setLojaForm({ ...lojaForm, ativa: v })} data-testid="loja-ativa-switch" />
                <Label htmlFor="loja-ativa" className="cursor-pointer">Loja ativa</Label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setLojaDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={savingLoja} data-testid="save-loja-btn">{savingLoja ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação de loja */}
      <AlertDialog open={!!deleteLojaTarget} onOpenChange={(o) => !o && setDeleteLojaTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar loja</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteLojaTarget?.nome}"? Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteLoja} className="bg-destructive text-destructive-foreground">Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Dialog criar/editar caixa */}
      <Dialog open={caixaDialogOpen} onOpenChange={setCaixaDialogOpen}>
        <DialogContent data-testid="caixa-dialog">
          <DialogHeader>
            <DialogTitle>{editingCaixa ? 'Editar caixa' : 'Nova caixa'}</DialogTitle>
            <DialogDescription>{caixaLoja ? `Loja: ${caixaLoja.nome}` : ''}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmitCaixa}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="caixa-nome">Nome *</Label>
                <Input
                  id="caixa-nome"
                  value={caixaForm.nome}
                  onChange={(e) => setCaixaForm({ ...caixaForm, nome: e.target.value })}
                  placeholder="Ex: Caixa 1"
                  required
                  maxLength={60}
                  data-testid="caixa-nome-input"
                />
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Switch id="caixa-ativa" checked={caixaForm.ativa} onCheckedChange={(v) => setCaixaForm({ ...caixaForm, ativa: v })} data-testid="caixa-ativa-switch" />
                <Label htmlFor="caixa-ativa" className="cursor-pointer">Caixa ativa</Label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCaixaDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={savingCaixa} data-testid="save-caixa-btn">{savingCaixa ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação de caixa */}
      <AlertDialog open={!!deleteCaixaTarget} onOpenChange={(o) => !o && setDeleteCaixaTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar caixa</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar a caixa "{deleteCaixaTarget?.caixa?.nome}"? Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteCaixa} className="bg-destructive text-destructive-foreground">Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
