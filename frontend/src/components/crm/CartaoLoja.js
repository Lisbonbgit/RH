// O cartão da loja no mapa (desenho original §6.1; plano T2.25): abre ao tocar
// num pino, por baixo do mapa, com o nome, a fase, o contacto (a pessoa de
// contacto e o telefone, em texto, só o que existe), a última ação e Ver
// ficha. Porta de public/assets/js/componentes/cartao-loja.js do CRM autónomo.
// O botão Ligar do desenho original saiu em 2026-10-13, a pedido do Bruce: o
// contacto lê-se no próprio cartão (`contactoDaLoja`, `lib/crm/ecraMapa.js`).
// O "Adicionar à rota" chega na F3 e a última ação na F5 (linha do tempo).
//
// O nome, a fase e o contacto entram como texto (o React escapa-os); não se
// monta nenhuma ligação com o telefone. O cartão não se fecha sozinho: o
// "Fechar" avisa a página (`aoFechar`), que também volta a medir o mapa.
import React, { useId } from 'react';
import { Link } from 'react-router-dom';
import { FileText, X } from 'lucide-react';
import { Button } from '../ui/button';
import { contactoDaLoja } from '../../lib/crm/ecraMapa';
import { FASES, ORDEM } from '../../lib/crm/fases';
import './crm.css';

export const TEXTO_ULTIMA_ACAO = 'Última ação: ainda sem histórico';

export default function CartaoLoja({ loja, base, aoFechar, refNome }) {
  const idNome = useId();
  const conhecida = ORDEM.includes(loja.fase);
  const contacto = contactoDaLoja(loja);

  return (
    <section
      role="dialog"
      aria-labelledby={idNome}
      className="relative z-[2] shrink-0 overflow-y-auto border-t bg-card px-4 pt-3 pb-[max(14px,env(safe-area-inset-bottom))] shadow-[0_-6px_18px_rgb(0_0_0/0.12)] md:px-6"
      data-testid="crm-cartao-loja"
    >
      <div className="mx-auto max-w-2xl">
        <div className="flex items-start justify-between gap-3">
          <h2
            id={idNome}
            ref={refNome}
            tabIndex={-1}
            className="min-w-0 pt-2 font-heading text-lg font-bold leading-snug [overflow-wrap:anywhere] focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
          >
            {loja.nome}
          </h2>
          <Button type="button" variant="ghost" className="h-11 shrink-0 gap-1.5" onClick={aoFechar}>
            <X className="h-4 w-4" aria-hidden="true" />
            Fechar
          </Button>
        </div>
        <p className="mt-0.5 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
          {conhecida && <span aria-hidden="true" className={`crm-amostra-fase pino--${loja.fase}`} />}
          {conhecida ? FASES[loja.fase].rotulo : String(loja.fase ?? '')}
        </p>
        {contacto && (
          <p className="mt-1 text-sm text-muted-foreground [overflow-wrap:anywhere]" data-testid="crm-cartao-contacto">
            <strong className="font-semibold text-foreground">Contacto:</strong> {contacto}
          </p>
        )}
        <p className="mb-3 mt-1 text-sm text-muted-foreground">
          <strong className="font-semibold text-foreground">Última ação:</strong> ainda sem histórico
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" className="h-11 flex-1 basis-36">
            <Link to={`${base}/lojas/${encodeURIComponent(loja.id)}`}>
              <FileText className="h-4 w-4" aria-hidden="true" />
              Ver ficha
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
