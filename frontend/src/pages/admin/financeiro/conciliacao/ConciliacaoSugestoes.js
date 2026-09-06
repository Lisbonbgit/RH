import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Link2, Check, X, ClipboardCheck, Wallet, AlertTriangle, Receipt } from 'lucide-react';
import { Card, CardContent } from '../../../../components/ui/card';
import { Button } from '../../../../components/ui/button';
import { Badge } from '../../../../components/ui/badge';
import MonthPicker from '../../../../components/MonthPicker';
import {
  getFinCompanies, getFinReconcileSuggestions, dismissFinReconcileSuggestion,
  getFinReconcilePending, runFinReconcileAuto, linkFinMovement,
} from '../../../../lib/api';
import { eur, fmtDate, kpiTone, todayISO } from '../../../../lib/finance';

const TODAS = 'all';

/**
 * As duas vistas de conciliação por sugestão, vindas do ecrã de Pagamentos.
 * `vista`: "sugestoes" (pares propostos pelo motor) ou "porligar" (fecho do mês).
 * Aceita companyId = "all": sem empresa escolhida no topo, agrega todas — o
 * mesmo que o Pagamentos fazia.
 */
export default function ConciliacaoSugestoes({ vista, companyId, month, aoMudar }) {
  const cid = companyId || TODAS;
  const [companies, setCompanies] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [sugBusyId, setSugBusyId] = useState(null);
  const [autoBusy, setAutoBusy] = useState(false);
  const [fecho, setFecho] = useState(null);
  const [fechoMonth, setFechoMonth] = useState(month || todayISO().slice(0, 7));
  const [fechoLoading, setFechoLoading] = useState(false);

  const companyName = (id) => (companies.find((c) => c.id === id) || {}).name || '';
  // Pode editar ESTA empresa? Em "todas", cada sugestão traz a sua.
  const podeEditarEmpresa = (id) => {
    const c = companies.find((x) => x.id === id);
    return !!c && (c.role === 'owner' || c.role === 'partner');
  };
  const podeCorrerAuto = companies.some((c) => c.role === 'owner' || c.role === 'partner');

  useEffect(() => {
    getFinCompanies().then(({ data }) => setCompanies(data || [])).catch(() => setCompanies([]));
  }, []);

  const loadSuggestions = useCallback(async () => {
    try {
      const r = await getFinReconcileSuggestions(cid);
      setSuggestions(r.data || []);
    } catch (e) {
      setSuggestions([]);
    }
  }, [cid]);

  const loadFecho = useCallback(async () => {
    setFechoLoading(true);
    try {
      const r = await getFinReconcilePending(cid, fechoMonth);
      setFecho(r.data);
    } catch (e) {
      setFecho(null);
    } finally {
      setFechoLoading(false);
    }
  }, [cid, fechoMonth]);

  useEffect(() => {
    if (vista === 'sugestoes') loadSuggestions();
    else loadFecho();
  }, [vista, loadSuggestions, loadFecho]);

  // Confirma uma sugestão: liga o movimento à fatura (marca-a paga).
  const confirmSuggestion = async (s) => {
    setSugBusyId(s.movement.id);
    try {
      await linkFinMovement(s.movement.id, s.invoice.id);
      toast.success('Fatura conciliada e marcada como paga');
      await loadSuggestions();
      if (aoMudar) aoMudar();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao conciliar');
    } finally {
      setSugBusyId(null);
    }
  };

  // Rejeita uma sugestão (não volta a aparecer este par).
  const rejectSuggestion = async (s) => {
    setSugBusyId(s.movement.id);
    try {
      await dismissFinReconcileSuggestion({ invoice_id: s.invoice.id, movement_id: s.movement.id });
      await loadSuggestions();
    } catch (e) {
      toast.error('Erro ao rejeitar');
    } finally {
      setSugBusyId(null);
    }
  };

  // Auto-confirmar agora: liga sozinho as que batem num carimbo já aprendido
  // (fornecedor que já confirmaste antes) + montante exato + par único.
  const runAutoReconcile = async () => {
    setAutoBusy(true);
    try {
      const r = await runFinReconcileAuto(cid);
      const n = (r.data && r.data.linked) || 0;
      if (n > 0) {
        toast.success(`${n} ${n === 1 ? 'fatura conciliada' : 'faturas conciliadas'} automaticamente`);
        await loadSuggestions();
        if (aoMudar) aoMudar();
      } else {
        toast.info('Nada para auto-confirmar. Só se marcam sozinhas as de fornecedores que já confirmaste antes.');
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao auto-confirmar');
    } finally {
      setAutoBusy(false);
    }
  };

  if (vista === 'sugestoes') {
    return (
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <Link2 className="h-4 w-4 text-primary mt-0.5 shrink-0" />
              <p className="text-sm text-muted-foreground max-w-2xl">
                Pagamentos prováveis detetados no extrato do banco. Confirma para marcar a fatura paga
                (com a data do movimento) ou rejeita se não corresponder. Cada confirmação <b>ensina</b> o
                sistema: da próxima vez, esse fornecedor marca-se sozinho.
              </p>
            </div>
            {podeCorrerAuto && (
              <Button size="sm" variant="outline" onClick={runAutoReconcile} disabled={autoBusy}
                data-testid="btn-auto-reconcile">
                <Check className="h-4 w-4 mr-1" />
                {autoBusy ? 'A confirmar...' : 'Auto-confirmar agora'}
              </Button>
            )}
          </div>
          {suggestions.length === 0 ? (
            <p className="text-center text-muted-foreground py-10 text-sm">
              Sem sugestões de momento. Importa o extrato do banco (no <b>Extrato</b>) para o sistema propor os pagamentos.
            </p>
          ) : (
            <div className="space-y-2">
              {suggestions.map((s) => (
                <div key={s.movement.id} className="rounded-xl border p-3 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={s.confianca === 'alta'
                      ? 'bg-emerald-600 hover:bg-emerald-600'
                      : 'bg-amber-500 hover:bg-amber-500'}>
                      {s.confianca === 'alta' ? 'Confiança alta' : 'Confiança média'}
                    </Badge>
                    {s.reasons.map((r) => (
                      <span key={r} className="text-[11px] rounded-md bg-muted px-1.5 py-0.5 text-muted-foreground">{r}</span>
                    ))}
                    {cid === TODAS && companyName(s.invoice.company_id) && (
                      <span className="text-[11px] text-muted-foreground">· {companyName(s.invoice.company_id)}</span>
                    )}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-[1fr_auto_1fr] items-center">
                    <div className="min-w-0">
                      <p className="text-xs text-muted-foreground">Fatura</p>
                      <p className="text-sm font-semibold truncate">{s.invoice.supplier || '(sem fornecedor)'}</p>
                      <p className="text-xs text-muted-foreground">
                        {s.invoice.invoice_number ? `nº ${s.invoice.invoice_number} · ` : ''}{eur(s.invoice.amount)}
                        {s.invoice.due_date ? ` · vence ${fmtDate(s.invoice.due_date)}` : ''}
                      </p>
                    </div>
                    <Link2 className="h-4 w-4 text-muted-foreground mx-auto hidden sm:block" />
                    <div className="min-w-0">
                      <p className="text-xs text-muted-foreground">Movimento do banco</p>
                      <p className="text-sm font-medium truncate">{fmtDate(s.movement.date_lancamento)} · {eur(s.movement.amount)}</p>
                      <p className="text-xs text-muted-foreground truncate">{s.movement.description || '—'}</p>
                    </div>
                  </div>
                  {podeEditarEmpresa(s.invoice.company_id) && (
                    <div className="flex justify-end gap-2 pt-1">
                      <Button size="sm" variant="ghost" disabled={sugBusyId === s.movement.id}
                        onClick={() => rejectSuggestion(s)} data-testid={`sug-reject-${s.movement.id}`}>
                        <X className="h-4 w-4 mr-1" />Rejeitar
                      </Button>
                      <Button size="sm" disabled={sugBusyId === s.movement.id}
                        onClick={() => confirmSuggestion(s)} data-testid={`sug-confirm-${s.movement.id}`}>
                        <Check className="h-4 w-4 mr-1" />{sugBusyId === s.movement.id ? 'A conciliar...' : 'Confirmar'}
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  // ---------- POR LIGAR (fecho de tesouraria) ----------
  return (
    <Card>
      <CardContent className="p-4 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-2">
            <ClipboardCheck className="h-4 w-4 text-primary mt-0.5 shrink-0" />
            <p className="text-sm text-muted-foreground max-w-2xl">
              Fecho do mês: o que ainda não bate. À esquerda, dinheiro que <b>saiu do banco</b> sem
              fatura associada. À direita, <b>faturas já vencidas</b> sem pagamento encontrado.
              Quando ambas as listas ficam vazias, o mês está fechado.
            </p>
          </div>
          <MonthPicker value={fechoMonth} onChange={setFechoMonth} className="w-44"
            testid="fin-porconciliar-month" />
        </div>

        {fechoLoading || !fecho ? (
          <p className="text-center text-muted-foreground py-10 text-sm">A carregar…</p>
        ) : (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="fin-porconciliar-kpis">
              {[
                { label: 'Movimentos conciliados',
                  value: `${fecho.totais.movimentos_ligados}/${fecho.totais.movimentos_mes}`,
                  icon: Check },
                { label: 'Movimentos por ligar', value: fecho.totais.movimentos_por_ligar_n, icon: Link2 },
                { label: 'Valor por ligar', value: eur(fecho.totais.movimentos_por_ligar_valor), icon: Wallet },
                { label: 'Faturas por pagar', value: eur(fecho.totais.faturas_por_pagar_valor), icon: AlertTriangle },
              ].map((k, i) => {
                const tone = kpiTone(i);
                return (
                  <Card key={k.label}>
                    <CardContent className="flex items-center gap-3 p-5">
                      <div className={`h-10 w-10 rounded-xl ${tone.bg} ${tone.icon} flex items-center justify-center shrink-0`}>
                        <k.icon className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-xl font-heading font-bold leading-none">{k.value}</p>
                        <p className="text-xs text-muted-foreground mt-1">{k.label}</p>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border">
                <div className="flex items-center gap-2 border-b px-4 py-2.5">
                  <Link2 className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm font-semibold">Saiu do banco, sem fatura</p>
                  <Badge variant="secondary" className="ml-auto">{fecho.movimentos_por_ligar.length}</Badge>
                </div>
                {fecho.movimentos_por_ligar.length === 0 ? (
                  <p className="text-center text-muted-foreground py-8 text-sm">Tudo ligado neste mês. ✅</p>
                ) : (
                  <div className="divide-y max-h-[28rem] overflow-y-auto">
                    {fecho.movimentos_por_ligar.map((m) => (
                      <div key={m.id} className="px-4 py-2.5" data-testid={`porconciliar-mov-${m.id}`}>
                        <div className="flex items-baseline justify-between gap-2">
                          <p className="text-sm font-medium">{fmtDate(m.date_lancamento)}</p>
                          <p className="text-sm font-semibold tabular-nums">{eur(m.amount)}</p>
                        </div>
                        <p className="text-xs text-muted-foreground truncate">{m.description || '—'}</p>
                        {cid === TODAS && companyName(m.company_id) && (
                          <p className="text-[11px] text-muted-foreground">{companyName(m.company_id)}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-xl border">
                <div className="flex items-center gap-2 border-b px-4 py-2.5">
                  <Receipt className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm font-semibold">Vencidas, sem pagamento</p>
                  <Badge variant="secondary" className="ml-auto">{fecho.faturas_por_pagar.length}</Badge>
                </div>
                {fecho.faturas_por_pagar.length === 0 ? (
                  <p className="text-center text-muted-foreground py-8 text-sm">Nada por pagar neste mês. ✅</p>
                ) : (
                  <div className="divide-y max-h-[28rem] overflow-y-auto">
                    {fecho.faturas_por_pagar.map((f) => (
                      <div key={f.id} className="px-4 py-2.5" data-testid={`porconciliar-inv-${f.id}`}>
                        <div className="flex items-baseline justify-between gap-2">
                          <p className="text-sm font-medium truncate">{f.supplier || '(sem fornecedor)'}</p>
                          <p className="text-sm font-semibold tabular-nums">{eur(f.amount)}</p>
                        </div>
                        <p className="text-xs text-muted-foreground truncate">
                          {f.invoice_number ? `nº ${f.invoice_number} · ` : ''}venceu {fmtDate(f.effective_due)}
                          {f.direct_debit ? ' · débito direto' : ''}
                        </p>
                        {cid === TODAS && companyName(f.company_id) && (
                          <p className="text-[11px] text-muted-foreground">{companyName(f.company_id)}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
