import React, { useState } from 'react';
import { Button } from './ui/button';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';
import { ChevronLeft, ChevronRight, CalendarDays } from 'lucide-react';

const MESES_FULL = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
const MESES_ABBR = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

/**
 * Seletor de mês/ano SÓ DE CLICAR (substitui o <input type="month"> nativo).
 * Clica nas setas para mudar o ano e clica no mês. value/onChange em "YYYY-MM".
 */
export default function MonthPicker({ value, onChange, className = '', testid }) {
  const now = new Date();
  const [y, m] = (value && /^\d{4}-\d{2}$/.test(value))
    ? value.split('-').map(Number)
    : [now.getFullYear(), now.getMonth() + 1];
  const [open, setOpen] = useState(false);
  const [viewYear, setViewYear] = useState(y);

  // Ao abrir, alinha o ano mostrado com o valor atual.
  const onOpenChange = (o) => { setOpen(o); if (o) setViewYear(y); };

  const choose = (mm) => {
    onChange(`${viewYear}-${String(mm).padStart(2, '0')}`);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" className={`justify-start font-normal ${className}`} data-testid={testid}>
          <CalendarDays className="h-4 w-4 mr-2 opacity-70 shrink-0" />
          {MESES_FULL[m - 1]} {y}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3" align="start">
        <div className="flex items-center justify-between mb-2">
          <Button variant="ghost" size="icon" className="h-7 w-7" title="Ano anterior"
            onClick={() => setViewYear((v) => v - 1)} data-testid="monthpicker-prev-year">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm font-heading font-semibold tabular-nums">{viewYear}</span>
          <Button variant="ghost" size="icon" className="h-7 w-7" title="Ano seguinte"
            onClick={() => setViewYear((v) => v + 1)} data-testid="monthpicker-next-year">
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <div className="grid grid-cols-3 gap-1">
          {MESES_ABBR.map((label, i) => {
            const mm = i + 1;
            const isSel = viewYear === y && mm === m;
            return (
              <button key={label} type="button" onClick={() => choose(mm)}
                className={`rounded-md px-2 py-1.5 text-sm transition-colors ${
                  isSel ? 'bg-primary text-primary-foreground font-medium'
                    : 'hover:bg-muted text-foreground'}`}>
                {label}
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
