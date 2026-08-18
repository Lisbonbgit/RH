import React, { useState } from 'react';
import { Calculator, Delete } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { temMaisDe2CasasDecimaisPos } from '@/lib/pos';

// Campo de dinheiro do POS: grande, com "um botão de calculadora ao lado"
// (do print do Vendus) — aqui um teclado táctil, a mesma ideia da entrada
// por PIN mas para um valor com casas decimais. Partilhado por três ecrãs
// do Task 2 (fundo em PosCaixaFechada, valor do movimento em PosMenuCaixa,
// contado em PosFecharCaixa) para não triplicar esta lógica.
//
// `valor` viaja sempre como STRING (nunca Number): é o mesmo raciocínio do
// PIN — um campo controlado que aceita ',' ou '.' e nunca deixa escrever
// uma segunda casa decimal, mas nunca arredonda nem "corrige" o que a
// funcionária está a escrever a meio.
export default function PosCampoValor({ id, label, valor, onChange, autoFocus, disabled }) {
  const [aberto, setAberto] = useState(false);

  const aceitarTexto = (texto) => {
    const comPonto = texto.replace(',', '.');
    const limpo = comPonto.replace(/[^0-9.]/g, '');
    const partes = limpo.split('.');
    const normalizado = partes.length > 2 ? partes[0] + '.' + partes.slice(1).join('') : limpo;
    onChange(normalizado);
  };

  const tocarDigito = (d) => aceitarTexto(valor + d);
  const tocarVirgula = () => { if (!valor.includes('.')) aceitarTexto(valor + '.'); };
  const apagar = () => onChange(valor.slice(0, -1));
  const limpar = () => onChange('');

  const excede2Casas = temMaisDe2CasasDecimaisPos(valor);

  return (
    <div className="space-y-1.5">
      {label && <label htmlFor={id} className="text-sm font-medium">{label}</label>}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-2xl font-heading font-bold text-muted-foreground pointer-events-none">
            €
          </span>
          <Input
            id={id}
            value={valor}
            onChange={(e) => aceitarTexto(e.target.value)}
            inputMode="decimal"
            autoFocus={autoFocus}
            disabled={disabled}
            placeholder="0,00"
            className="h-16 pl-11 pr-4 text-3xl font-heading font-bold text-right"
          />
        </div>
        <Popover open={aberto} onOpenChange={setAberto}>
          <PopoverTrigger asChild>
            <Button type="button" variant="outline" size="icon" disabled={disabled} className="h-16 w-16 shrink-0" aria-label="Abrir calculadora">
              <Calculator className="h-6 w-6" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-64" align="end">
            <div className="grid grid-cols-3 gap-2">
              {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => tocarDigito(d)}
                  className="h-12 rounded-lg border bg-card text-lg font-semibold hover:bg-accent active:scale-95 transition-transform"
                >
                  {d}
                </button>
              ))}
              <button
                type="button"
                onClick={tocarVirgula}
                className="h-12 rounded-lg border bg-card text-lg font-semibold hover:bg-accent active:scale-95 transition-transform"
              >
                ,
              </button>
              <button
                type="button"
                onClick={() => tocarDigito('0')}
                className="h-12 rounded-lg border bg-card text-lg font-semibold hover:bg-accent active:scale-95 transition-transform"
              >
                0
              </button>
              <button
                type="button"
                onClick={apagar}
                aria-label="Apagar"
                className="h-12 rounded-lg border bg-card flex items-center justify-center hover:bg-accent active:scale-95 transition-transform"
              >
                <Delete className="h-5 w-5" />
              </button>
            </div>
            <Button type="button" variant="ghost" size="sm" className="w-full mt-2" onClick={limpar}>
              Limpar
            </Button>
          </PopoverContent>
        </Popover>
      </div>
      {excede2Casas && <p className="text-xs text-destructive">Não pode ter mais de 2 casas decimais.</p>}
    </div>
  );
}
