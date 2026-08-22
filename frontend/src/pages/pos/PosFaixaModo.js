import React from 'react';
import { ShieldAlert, HelpCircle } from 'lucide-react';
import { faixaDoModo } from '@/lib/pos';

// A faixa que diz em que modo o POS está a emitir.
//
// **Não decide nada.** Os três estados decidem-se em `lib/pos.js::faixaDoModo`,
// que um teste corre mesmo em Node — é o oposto de uma condição escrita no meio
// do JSX, que não se executa em lado nenhum e fica verde desligada. Aqui só se
// desenha o que essa função devolver, e `null` desenha exactamente nada.
//
// **Onde ela vive, e porque não rouba espaço.** Vai DENTRO da barra de cima que
// já existe (`PosMenuCaixa`, e o `TopoSimples` do `PosApp` com a caixa
// fechada), no vão que o `justify-between` já deixava vazio entre a identidade
// da loja e o botão «Caixa». Em `normal` não desenha um único pixel e a barra
// fica byte a byte como hoje — o dono queixou-se de o ecrã do POS ser grande de
// mais e pediu uma área de trabalho mais contida, como a do Vendus, e o estado
// normal de trabalho não pode pagar espaço a um aviso que não tem nada para
// avisar. Nos outros dois estados, o que muda de cor é a barra inteira do topo
// do ecrã: sem um pixel a mais de altura, e impossível de não ver.
//
// **`role="alert"`** e não um `title` discreto: é uma frase que tem de chegar a
// quem não está a olhar para ela, e a um leitor de ecrã também.

const TONS = {
  // `tests`: âmbar cheio. As faturas não valem nada, mas o POS trabalha.
  alarme: {
    caixa: 'border-warning bg-warning text-black',
    Icone: ShieldAlert,
  },
  // O terceiro estado: vermelho. Não se sabe o que está a sair, e o que se
  // pede é diferente — parar.
  perigo: {
    caixa: 'border-destructive bg-destructive text-destructive-foreground',
    Icone: HelpCircle,
  },
};

export default function PosFaixaModo({ estado }) {
  const faixa = faixaDoModo(estado);
  if (!faixa) return null;

  const tom = TONS[faixa.tom] || TONS.perigo;
  const { Icone } = tom;

  return (
    <div
      role="alert"
      className={`flex min-w-0 flex-1 items-center justify-center gap-2 rounded-lg border-2 px-3 py-1.5 ${tom.caixa}`}
    >
      <Icone className="h-5 w-5 shrink-0 animate-pulse" />
      <div className="min-w-0 leading-tight">
        <p className="font-heading text-xs font-bold uppercase tracking-wide sm:text-sm">
          {faixa.titulo}
        </p>
        {/* O porquê fica escondido nos ecrãs estreitos e o título não: numa
            barra de 64 px de altura o que tem de caber sempre é a frase que
            faz parar. */}
        <p className="hidden text-xs lg:block">{faixa.texto}</p>
      </div>
    </div>
  );
}
