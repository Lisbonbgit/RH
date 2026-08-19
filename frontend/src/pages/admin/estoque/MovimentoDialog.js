import React, { useState } from 'react';
import { estoqueMovimento, estoqueTransferencia } from '../../../lib/api';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../components/ui/dialog';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { toast } from 'sonner';

const fmt = (n) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return '0';
  return (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)).replace('.', ',');
};
const parseNum = (v) => {
  const n = Number(String(v ?? '').trim().replace(',', '.'));
  return Number.isFinite(n) ? n : NaN;
};

const MOVS = [
  { tipo: 'entrada', label: 'Entrada' },
  { tipo: 'saida', label: 'Saída' },
  { tipo: 'contagem', label: 'Contagem' },
];

// Painel de operação de um produto numa loja, aberto a partir do Stock do portal
// RH: Entrada/Saída/Contagem + Transferência direta para outra loja da mesma marca.
export default function MovimentoDialog({ item, lojaId, lojaNome, lojas, onClose, onDone }) {
  const [qtds, setQtds] = useState({ entrada: '', saida: '', contagem: '', transferir: '' });
  const [destino, setDestino] = useState('');
  const [saving, setSaving] = useState(false);

  if (!item) return null;

  const marca = lojas.find((l) => l.id === lojaId)?.marca;
  const destinos = lojas.filter((l) => l.id !== lojaId && l.marca === marca);
  const setQ = (k, v) => setQtds((s) => ({ ...s, [k]: v }));
  const medida = item.unidade_medida;

  async function registar(tipo) {
    if (qtds[tipo].trim() === '') return toast.error('Escreve a quantidade primeiro.');
    const q = parseNum(qtds[tipo]);
    if (Number.isNaN(q) || (tipo === 'contagem' ? q < 0 : q <= 0)) return toast.error('Quantidade inválida.');
    setSaving(true);
    try {
      const r = await estoqueMovimento({ tipo, unidade_id: lojaId, produto_id: item.produto_id, quantidade: q });
      toast.success(`${item.nome}: agora ${fmt(r.data.quantidade_atual)} ${medida}.`);
      onDone();
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível registar.');
    } finally {
      setSaving(false);
    }
  }

  async function transferir() {
    if (qtds.transferir.trim() === '') return toast.error('Escreve a quantidade a transferir.');
    const q = parseNum(qtds.transferir);
    if (Number.isNaN(q) || q <= 0) return toast.error('Quantidade inválida.');
    if (!destino) return toast.error('Escolhe a loja de destino.');
    setSaving(true);
    try {
      await estoqueTransferencia({
        unidade_id: lojaId,
        destino_unidade_id: destino,
        produto_id: item.produto_id,
        quantidade: q,
      });
      const nome = destinos.find((d) => d.id === destino)?.nome || 'destino';
      toast.success(`${item.nome}: ${fmt(q)} ${medida} transferido para ${nome}.`);
      onDone();
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível transferir.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{item.nome}</DialogTitle>
          <DialogDescription>
            {lojaNome} · em stock: <span className="font-medium text-foreground">{fmt(item.quantidade_atual)} {medida}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          {MOVS.map((m) => (
            <div key={m.tipo} className="flex items-center gap-2">
              <Input
                inputMode="decimal"
                placeholder={m.label}
                value={qtds[m.tipo]}
                onChange={(e) => setQ(m.tipo, e.target.value)}
                className="flex-1"
                data-testid={`mov-${m.tipo}`}
              />
              <Button
                type="button"
                variant={m.tipo === 'entrada' ? 'default' : 'outline'}
                className="w-32 shrink-0"
                disabled={saving}
                onClick={() => registar(m.tipo)}
              >
                {m.label}
              </Button>
            </div>
          ))}
        </div>

        {destinos.length > 0 && (
          <div className="pt-3 mt-1 border-t space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Transferir para outra loja</p>
            <div className="flex items-center gap-2">
              <Input
                inputMode="decimal"
                placeholder="Qtd."
                value={qtds.transferir}
                onChange={(e) => setQ('transferir', e.target.value)}
                className="w-24 shrink-0"
                data-testid="mov-transferir"
              />
              <Select value={destino} onValueChange={setDestino}>
                <SelectTrigger className="flex-1" data-testid="mov-destino">
                  <SelectValue placeholder="Loja de destino" />
                </SelectTrigger>
                <SelectContent>
                  {destinos.map((d) => (
                    <SelectItem key={d.id} value={d.id}>{d.nome}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button type="button" variant="outline" className="w-32 shrink-0" disabled={saving} onClick={transferir}>
                Transferir
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
