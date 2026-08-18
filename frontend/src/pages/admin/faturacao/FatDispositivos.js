import React, { useEffect, useState } from 'react';
import {
  getDispositivosPos, gerarCodigoDispositivo, revogarDispositivo, getLojas,
  detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
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
import { Smartphone, Plus, Trash2, Copy, Check, Clock } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const emptyForm = { loja_id: '', nome: '' };

// Mesmo padrão de PosMenuCaixa.js — "dd/mm/aaaa às hh:mm".
const formatarData = (isoString) => {
  if (!isoString) return null;
  try {
    const d = new Date(isoString);
    const data = d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit', year: 'numeric' });
    const hora = d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
    return `${data} às ${hora}`;
  } catch (e) {
    return null;
  }
};

// Separa o código de 8 caracteres a meio ("3F9A 2B7C") — mais fácil de ler
// e ditar ao telefone do que uma sequência corrida.
const formatarCodigo = (codigo) => {
  if (!codigo) return '';
  const meio = Math.ceil(codigo.length / 2);
  return `${codigo.slice(0, meio)} ${codigo.slice(meio)}`;
};

const mmss = (segundos) =>
  `${String(Math.floor(segundos / 60)).padStart(2, '0')}:${String(segundos % 60).padStart(2, '0')}`;

const estadoBadge = (estado) => (
  estado === 'activo'
    ? <Badge variant="outline" className="bg-teal-50 text-teal-700 border-teal-200">Ativo</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Revogado</Badge>
);

export default function FatDispositivos() {
  const [dispositivos, setDispositivos] = useState([]);
  const [lojas, setLojas] = useState([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [gerando, setGerando] = useState(false);

  // { codigo, expira_em, lojaNome, nome } — o diálogo do código gerado,
  // mostrado assim que o pedido de código responde.
  const [codigoInfo, setCodigoInfo] = useState(null);
  const [segundosRestantes, setSegundosRestantes] = useState(0);
  const [copiado, setCopiado] = useState(false);

  const [revokeTarget, setRevokeTarget] = useState(null);
  const [revoking, setRevoking] = useState(false);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [d, l] = await Promise.all([getDispositivosPos(), getLojas()]);
      setDispositivos(d.data || []);
      setLojas(l.data || []);
    } catch (error) {
      toast.error('Erro ao carregar dispositivos');
    } finally {
      setLoading(false);
    }
  };

  const lojasPorId = Object.fromEntries(lojas.map((l) => [l.id, l]));

  // Contagem decrescente até expira_em, enquanto o diálogo do código estiver
  // aberto — o gestor está ao telefone com a loja e precisa de ver o tempo a
  // esgotar-se em tempo real, não só ao abrir o diálogo.
  useEffect(() => {
    if (!codigoInfo) return undefined;
    const calcular = () => {
      const restam = Math.round((new Date(codigoInfo.expira_em).getTime() - Date.now()) / 1000);
      setSegundosRestantes(Math.max(0, restam));
    };
    calcular();
    const intervalo = setInterval(calcular, 1000);
    return () => clearInterval(intervalo);
  }, [codigoInfo]);

  const openNew = () => {
    setForm(emptyForm);
    setDialogOpen(true);
  };

  const handleGerar = async (e) => {
    e.preventDefault();
    if (!form.loja_id) { toast.error('Escolha a loja'); return; }
    setGerando(true);
    try {
      const { data } = await gerarCodigoDispositivo({
        loja_id: form.loja_id,
        nome: form.nome.trim() || null,
      });
      setDialogOpen(false);
      setCopiado(false);
      setCodigoInfo({
        codigo: data.codigo,
        expira_em: data.expira_em,
        lojaNome: lojasPorId[form.loja_id]?.nome || '',
        nome: form.nome.trim(),
      });
    } catch (error) {
      const { mensagem } = detalhesErro(error, 'Erro ao gerar o código');
      toast.error(mensagem);
    } finally {
      setGerando(false);
    }
  };

  const handleCopiar = async () => {
    try {
      await navigator.clipboard.writeText(codigoInfo.codigo);
      setCopiado(true);
      toast.success('Código copiado');
      setTimeout(() => setCopiado(false), 2000);
    } catch (error) {
      toast.error('Não foi possível copiar. Copie o código manualmente.');
    }
  };

  const fecharCodigo = () => {
    setCodigoInfo(null);
    // O dispositivo só aparece na lista depois de o próprio PC trocar o
    // código pelo token (POST /pos/emparelhar) — por via das dúvidas, se
    // isso já aconteceu enquanto o diálogo estava aberto, atualiza a lista.
    fetchAll();
  };

  const handleRevoke = async () => {
    const alvo = revokeTarget;
    setRevokeTarget(null);
    setRevoking(true);
    try {
      await revogarDispositivo(alvo.id);
      toast.success('Dispositivo revogado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este dispositivo já não existe ou já estava revogado. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao revogar o dispositivo');
      }
    } finally {
      setRevoking(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-dispositivos-page">
      <PageHeader icon={Smartphone} title="Dispositivos" subtitle="PCs autorizados a abrir o POS, loja a loja">
        <Button onClick={openNew} data-testid="add-dispositivo-btn"><Plus className="h-4 w-4 mr-2" />Autorizar um PC</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : dispositivos.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-6">
              <Smartphone className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem dispositivos autorizados</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md">
                Cada PC de uma loja precisa de ser autorizado uma vez antes de conseguir abrir o POS.
                Gere um código de emparelhamento e introduza-o naquele PC para o autorizar.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>PC</TableHead>
                    <TableHead>Loja</TableHead>
                    <TableHead>Última atividade</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dispositivos.map((d) => (
                    <TableRow key={d.id} data-testid={`dispositivo-row-${d.id}`}>
                      <TableCell className="font-medium">{d.nome || '—'}</TableCell>
                      <TableCell>{lojasPorId[d.loja_id]?.nome || d.loja_id}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{formatarData(d.ultima_atividade_em) || 'Nunca'}</TableCell>
                      <TableCell>{estadoBadge(d.estado)}</TableCell>
                      <TableCell className="text-right">
                        {d.estado === 'activo' && (
                          <Button variant="ghost" size="icon" title="Revogar" onClick={() => setRevokeTarget(d)} data-testid={`revoke-dispositivo-${d.id}`}>
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
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

      {/* Dialog: escolher loja + nome do PC */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="dispositivo-dialog">
          <DialogHeader>
            <DialogTitle>Autorizar um PC</DialogTitle>
            <DialogDescription>
              Gera um código de uso único. Introduza-o no PC da loja para o autorizar a abrir o POS.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleGerar}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>Loja *</Label>
                <Select value={form.loja_id} onValueChange={(v) => setForm({ ...form, loja_id: v })}>
                  <SelectTrigger data-testid="dispositivo-loja-select"><SelectValue placeholder="Selecionar loja" /></SelectTrigger>
                  <SelectContent>
                    {lojas.map((l) => (
                      <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {lojas.length === 0 && (
                  <p className="text-xs text-muted-foreground">Sem lojas criadas ainda.</p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="dispositivo-nome">Nome deste PC</Label>
                <Input
                  id="dispositivo-nome"
                  value={form.nome}
                  onChange={(e) => setForm({ ...form, nome: e.target.value })}
                  placeholder="Ex: PC do balcão"
                  maxLength={60}
                  data-testid="dispositivo-nome-input"
                />
                <p className="text-xs text-muted-foreground">Para o reconhecer depois na lista — ex.: "PC do balcão", "Portátil da Amadora".</p>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={gerando || !form.loja_id} data-testid="gerar-codigo-btn">{gerando ? 'A gerar...' : 'Gerar código'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Dialog: código gerado — grande, legível de longe, fácil de copiar */}
      <Dialog open={!!codigoInfo} onOpenChange={(o) => !o && fecharCodigo()}>
        <DialogContent data-testid="codigo-dialog" className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Código de emparelhamento</DialogTitle>
            <DialogDescription>
              {codigoInfo?.lojaNome}{codigoInfo?.nome ? ` · ${codigoInfo.nome}` : ''}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col items-center gap-3 py-2">
            <div
              className="font-mono font-bold tracking-[0.3em] text-4xl sm:text-5xl bg-muted rounded-xl px-6 py-5 text-center select-all"
              data-testid="codigo-valor"
            >
              {formatarCodigo(codigoInfo?.codigo)}
            </div>
            <Button type="button" variant="outline" onClick={handleCopiar} data-testid="copiar-codigo-btn">
              {copiado ? <Check className="h-4 w-4 mr-2" /> : <Copy className="h-4 w-4 mr-2" />}
              {copiado ? 'Copiado' : 'Copiar código'}
            </Button>
            <div
              className={`flex items-center gap-1.5 text-sm font-medium ${segundosRestantes > 0 && segundosRestantes <= 60 ? 'text-destructive' : 'text-muted-foreground'}`}
              data-testid="codigo-expira"
            >
              <Clock className="h-3.5 w-3.5" />
              {segundosRestantes > 0
                ? `Expira em ${mmss(segundosRestantes)}`
                : 'Código expirado — gere um novo.'}
            </div>
          </div>

          <div className="rounded-lg border bg-muted/40 p-3 text-sm space-y-2">
            <p className="font-medium">Uso único: este código autoriza um PC. Para outro PC, gere um código novo.</p>
            <p className="text-muted-foreground">
              O que a pessoa na loja tem de fazer: abrir <span className="font-medium text-foreground">rh.lisbonb.com/faturacao/pos</span> naquele PC e colar o código.
            </p>
          </div>

          <DialogFooter>
            <Button type="button" onClick={fecharCodigo} data-testid="fechar-codigo-btn">Concluído</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirmar revogação */}
      <AlertDialog open={!!revokeTarget} onOpenChange={(o) => !o && setRevokeTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revogar dispositivo</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende revogar "{revokeTarget?.nome || 'este PC'}"? A partir daqui, o POS desse PC deixa de abrir.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleRevoke} disabled={revoking} className="bg-destructive text-destructive-foreground">
              {revoking ? 'A revogar...' : 'Revogar'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
