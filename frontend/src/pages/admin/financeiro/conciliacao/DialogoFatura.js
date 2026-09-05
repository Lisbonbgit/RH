import React, { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Link2, Paperclip, X } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '../../../../components/ui/dialog';
import { Button } from '../../../../components/ui/button';
import { Input } from '../../../../components/ui/input';
import { Badge } from '../../../../components/ui/badge';
import {
  getFinReconcileSuggestions, getFinInvoices,
  linkFinMovement, unlinkFinMovement, attachFinMovement,
} from '../../../../lib/api';
import { eur, fmtDate, normSup } from '../../../../lib/finance';
import { descricaoDoMovimento } from '../../../../lib/conciliacao';

export default function DialogoFatura({ movimento, companyId, aberto, aoFechar, aoMudar }) {
  const [sugestoes, setSugestoes] = useState([]);
  const [faturas, setFaturas] = useState([]);
  const [procura, setProcura] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const ficheiroRef = useRef(null);

  useEffect(() => {
    if (!aberto || !movimento) return;
    setProcura('');
    getFinReconcileSuggestions(companyId)
      .then(({ data }) => setSugestoes((data || []).filter((s) => s.movement && s.movement.id === movimento.id)))
      .catch(() => setSugestoes([]));
    getFinInvoices(companyId)
      .then(({ data }) => setFaturas((data || []).filter((f) => !f.paid || f.id === movimento.invoice_id)))
      .catch(() => setFaturas([]));
  }, [aberto, movimento, companyId]);

  const encontradas = useMemo(() => {
    const q = normSup(procura);
    if (!q) return faturas.slice(0, 20);
    return faturas.filter((f) =>
      normSup(f.supplier || '').includes(q) || String(f.invoice_number || '').includes(procura),
    ).slice(0, 20);
  }, [faturas, procura]);

  if (!movimento) return null;

  const ligar = async (invoiceId) => {
    setOcupado(true);
    try {
      await linkFinMovement(movimento.id, invoiceId);
      toast.success('Fatura ligada.');
      aoMudar();
      aoFechar();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível ligar.');
    } finally { setOcupado(false); }
  };

  const desligar = async () => {
    setOcupado(true);
    try {
      await unlinkFinMovement(movimento.id);
      toast.success('Fatura desligada. Voltou a "por pagar".');
      aoMudar();
      aoFechar();
    } catch (e) {
      toast.error('Não foi possível desligar.');
    } finally { setOcupado(false); }
  };

  const anexar = async (file) => {
    if (!file) return;
    setOcupado(true);
    try {
      await attachFinMovement(movimento.id, file);
      toast.success('Documento anexado.');
      aoMudar();
      aoFechar();
    } catch (e) {
      toast.error('Não foi possível anexar.');
    } finally { setOcupado(false); }
  };

  return (
    <Dialog open={aberto} onOpenChange={(o) => !o && aoFechar()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{descricaoDoMovimento(movimento)}</DialogTitle>
          <DialogDescription>
            {fmtDate(movimento.date_lancamento)} · {eur(movimento.amount)}
          </DialogDescription>
        </DialogHeader>

        {movimento.invoice_id ? (
          <div className="rounded-xl border p-3 flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-semibold truncate">Fatura ligada</p>
              <p className="text-xs text-muted-foreground">
                Desligar repõe a fatura como "por pagar".
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={desligar} disabled={ocupado}>
              <X className="h-4 w-4 mr-1" />Desligar
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {!!sugestoes.length && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Sugestões</p>
                {sugestoes.map((s) => (
                  <div key={s.invoice.id} className="rounded-xl border p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold truncate">
                          {s.invoice.supplier} · {s.invoice.invoice_number || 's/nº'}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {fmtDate(s.invoice.issue_date)} · {eur(s.invoice.amount)}
                        </p>
                      </div>
                      <Badge className={s.confianca === 'alta'
                        ? 'bg-emerald-600 hover:bg-emerald-600'
                        : 'bg-amber-500 hover:bg-amber-500'}>
                        {s.confianca === 'alta' ? 'Confiança alta' : 'Confiança média'}
                      </Badge>
                    </div>
                    <div className="flex justify-end">
                      <Button size="sm" disabled={ocupado} onClick={() => ligar(s.invoice.id)}>
                        <Link2 className="h-4 w-4 mr-1" />Ligar
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Procurar fatura
              </p>
              <Input value={procura} onChange={(e) => setProcura(e.target.value)}
                placeholder="Fornecedor ou número" data-testid="fin-conc-procura" />
              <div className="max-h-56 overflow-y-auto space-y-1">
                {encontradas.map((f) => (
                  <button key={f.id} type="button" disabled={ocupado} onClick={() => ligar(f.id)}
                    className="w-full text-left rounded-lg border p-2 hover:bg-muted/50">
                    <p className="text-sm font-medium truncate">
                      {f.supplier} · {f.invoice_number || 's/nº'}
                      {f.source === 'estoque' && <Badge variant="outline" className="ml-2 text-[10px]">loja</Badge>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {fmtDate(f.issue_date)} · {eur(f.amount)}
                    </p>
                  </button>
                ))}
                {!encontradas.length && (
                  <p className="text-xs text-muted-foreground py-2">Nenhuma fatura por pagar encontrada.</p>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="pt-2 border-t">
          <input ref={ficheiroRef} type="file" accept=".pdf" className="hidden"
            onChange={(e) => { anexar(e.target.files && e.target.files[0]); e.target.value = ''; }} />
          <Button variant="outline" size="sm" disabled={ocupado}
            onClick={() => ficheiroRef.current && ficheiroRef.current.click()} data-testid="fin-conc-anexar">
            <Paperclip className="h-4 w-4 mr-2" />
            {movimento.attachment_path ? 'Substituir o documento anexado' : 'Anexar um documento'}
          </Button>
          <p className="text-[11px] text-muted-foreground mt-1">
            É um anexo por linha: anexar outro substitui o que lá está.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
