import React, { useEffect, useState } from 'react';
import { ShieldAlert, HelpCircle, BadgeCheck } from 'lucide-react';
import { estadoDoModoLido, avisoDoModoNoBackoffice } from '../../../lib/pos';
import { getModoDeEmissaoDoBackoffice } from '../../../lib/faturacao';

// «Neste momento está tudo em teste né? posso fazer faturas aqui normal.»
//
// Foi a pergunta do dono, e ninguém soube responder sem ir ao servidor ler uma
// variável de ambiente. É esta linha que a responde — no sítio onde ele decide.
//
// **Não decide nada.** Os três estados decidem-se em `lib/pos.js`
// (`estadoDoModoLido` + `avisoDoModoNoBackoffice`), onde um teste os corre.
// Importam-se de lá só funções PURAS: a instância de axios do POS fica onde
// está (é isolada de propósito — ver o cabeçalho do lib/pos.js) e a chamada de
// rede desta página é a do backoffice, com o JWT de gestão.
//
// **`normal` aqui responde, ao contrário do POS.** É a única saída deliberada
// da regra dos três estados, e está explicada em `avisoDoModoNoBackoffice`: o
// balcão vive em `normal` o dia inteiro e uma faixa permanente ensinava a
// operadora a ignorar as outras duas; o gestor entra aqui precisamente para
// confirmar, e um ecrã calado obrigava-o a saber de cor que o silêncio quer
// dizer «sim».

const TONS = {
  calmo: {
    caixa: 'border-border bg-muted/50 text-muted-foreground',
    icone: 'text-success',
    Icone: BadgeCheck,
  },
  alarme: {
    caixa: 'border-warning bg-warning/10',
    icone: 'text-warning',
    Icone: ShieldAlert,
  },
  perigo: {
    caixa: 'border-destructive bg-destructive/10',
    icone: 'text-destructive',
    Icone: HelpCircle,
  },
};

export default function FatModoDeEmissao() {
  // `undefined` até o servidor responder — e `avisoDoModoNoBackoffice` lê isso
  // como o terceiro estado, nunca como `normal`. O valor inicial de um estado
  // do React é uma resposta que ninguém deu.
  const [estado, setEstado] = useState(undefined);

  // `estadoDoModoLido` nunca rejeita (o `catch` está lá dentro): sem rede, sem
  // rota ou com uma resposta que não se percebe, o que chega é 'desconhecido'.
  useEffect(() => {
    let vivo = true;
    estadoDoModoLido(getModoDeEmissaoDoBackoffice)
      .then((lido) => { if (vivo) setEstado(lido); });
    return () => { vivo = false; };
  }, []);

  const aviso = avisoDoModoNoBackoffice(estado);
  const tom = TONS[aviso.tom] || TONS.perigo;
  const { Icone } = tom;

  return (
    <div
      role={aviso.tom === 'calmo' ? undefined : 'alert'}
      className={`flex items-start gap-3 rounded-xl border-2 px-4 py-3 ${tom.caixa}`}
      data-testid="fat-modo-de-emissao"
    >
      <Icone className={`h-5 w-5 shrink-0 mt-0.5 ${tom.icone}`} />
      <div className="min-w-0">
        <p className="font-heading font-bold text-sm">{aviso.titulo}</p>
        <p className="text-sm mt-0.5">{aviso.texto}</p>
      </div>
    </div>
  );
}
