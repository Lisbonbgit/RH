import React, { useMemo } from 'react';
import { Card, CardContent } from '../../../../components/ui/card';
import { Landmark, PieChart, Store, Receipt } from 'lucide-react';
import { eur, kpiTone } from '../../../../lib/finance';
import {
  resumoPorCategoria, percentagensSobreEntradas, plataformasDasEntradas,
} from '../../../../lib/conciliacao';

// Linha label/valor, igual à do relatório de Resultados.
function Linha({ label, value, bold, muted }) {
  return (
    <div className="flex items-center justify-between">
      <span className={`text-sm ${muted ? 'text-muted-foreground' : ''}`}>{label}</span>
      <span className={`text-sm tabular-nums ${bold ? 'font-bold font-heading' : ''}`}>{value}</span>
    </div>
  );
}

function Bloco({ titulo, icone: Icone, cor, children }) {
  const tone = kpiTone(cor);
  return (
    <Card><CardContent className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <div className={`h-8 w-8 rounded-lg ${tone.bg} ${tone.icon} flex items-center justify-center shrink-0`}>
          <Icone className="h-4 w-4" />
        </div>
        <p className="text-sm font-semibold">{titulo}</p>
      </div>
      <div className="space-y-1">{children}</div>
    </CardContent></Card>
  );
}

export default function ConciliacaoCartoes({ movimentos, categorias, saldos, pendentes }) {
  const resumo = useMemo(() => resumoPorCategoria(movimentos, categorias), [movimentos, categorias]);
  const pcts = useMemo(() => percentagensSobreEntradas(resumo), [resumo]);
  const plataformas = useMemo(() => plataformasDasEntradas(movimentos), [movimentos]);

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Bloco titulo="Resumo do orçamento" icone={PieChart} cor={0}>
        {resumo.map((l) => (
          // Valor absoluto, como no Excel: o sinal já se lê na categoria.
          <Linha key={l.id} label={l.label} value={eur(Math.abs(l.total))}
            muted={l.total === 0} bold={l.id === 'entradas'} />
        ))}
      </Bloco>

      <Bloco titulo="Resumo em %" icone={PieChart} cor={1}>
        {pcts.map((p) => (
          <Linha key={p.id} label={p.label}
            value={p.pct === null ? '—' : `${p.pct.toLocaleString('pt-PT', { maximumFractionDigits: 2 })}%`} />
        ))}
        {!pcts.length && (
          <p className="text-xs text-muted-foreground">Sem despesas classificadas neste mês.</p>
        )}
        {!!pcts.length && pcts.every((p) => p.pct === null) && (
          <p className="text-xs text-muted-foreground">Sem entradas neste mês: não há por onde dividir.</p>
        )}
      </Bloco>

      <Bloco titulo="Valor Contas" icone={Landmark} cor={2}>
        {(saldos?.contas || []).map((c) => (
          <Linha key={c.account_id} label={c.name || c.bank || 'Conta'}
            value={c.balance === null ? '—' : eur(c.balance)} />
        ))}
        {!(saldos?.contas || []).length && (
          <p className="text-xs text-muted-foreground">Sem contas bancárias nesta empresa.</p>
        )}
        {!!(saldos?.contas || []).length && (
          <div className="pt-2 mt-1 border-t">
            <Linha label="Total" value={eur(saldos.total)} bold />
          </div>
        )}
      </Bloco>

      <div className="space-y-4">
        <Bloco titulo="Plataformas" icone={Store} cor={3}>
          {plataformas.length
            ? plataformas.map((p) => <Linha key={p.nome} label={p.nome} value={eur(p.total)} />)
            : <p className="text-xs text-muted-foreground">
                Classifica as entradas para elas aparecerem aqui.
              </p>}
          {!!plataformas.length && (
            <div className="pt-2 mt-1 border-t">
              <Linha label="Total" value={eur(plataformas.reduce((s, p) => s + p.total, 0))} bold />
            </div>
          )}
        </Bloco>
        <Bloco titulo="Faturas por pagar" icone={Receipt} cor={4}>
          <Linha label="Total" value={eur(pendentes?.totais?.faturas_por_pagar_valor || 0)} bold />
          <Linha label="Movimentos por ligar"
            value={String(pendentes?.totais?.movimentos_por_ligar_n ?? '—')} muted />
        </Bloco>
      </div>
    </div>
  );
}
