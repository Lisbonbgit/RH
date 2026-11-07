// O cartão da loja no mapa (desenho original §6.1; plano T2.25): abre ao tocar
// num pino, por baixo do mapa, com o nome, a fase, o contacto (a pessoa de
// contacto e o telefone, em texto, só o que existe), o último contacto e Ver
// ficha. Porta de public/assets/js/componentes/cartao-loja.js do CRM autónomo.
// O botão Ligar do desenho original saiu em 2026-10-13, a pedido do Bruce: o
// contacto lê-se no próprio cartão (`contactoDaLoja`, `lib/crm/ecraMapa.js`).
// "Adicionar à rota" (F3, plano T3.40; ícone `Route`) avisa a página
// (`aoAdicionarARota`), que abre o diálogo de escolher o dia e o motivo
// (`DialogoAdicionarARota`); o botão (`refAdicionar`) recebe o foco quando o
// diálogo fecha. O último contacto sai do `linhaUltimoContacto`
// (`lib/crm/ecraMapa.js`), lido do resumo do `GET /lojas`.
//
// O nome, a fase e o contacto entram como texto (o React escapa-os); não se
// monta nenhuma ligação com o telefone. O cartão não se fecha sozinho: o
// "Fechar" avisa a página (`aoFechar`), que também volta a medir o mapa.
// Fica encostado ao fundo do mapa, onde estão o logótipo e a atribuição da
// Google: só o filete de cima o separa, sem sombra lançada para cima, que se
// pintava sobre eles (revisão do mapa Google, MAPA-G-5; `css.test.js`).
import React, { useId } from 'react';
import { Link } from 'react-router-dom';
import { FileText, Route as IconeRota, X } from 'lucide-react'; // nunca `Route`: confundia-se com o do React Router
import { Button } from '../ui/button';
import { TITULO_ADICIONAR_A_ROTA } from '../../lib/crm/adicionarARota';
import { contactoDaLoja, linhaUltimoContacto } from '../../lib/crm/ecraMapa';
import { FASES, ORDEM } from '../../lib/crm/fases';
import './crm.css';

export default function CartaoLoja({
  loja, base, aoFechar, refNome, aoAdicionarARota, refAdicionar,
}) {
  const idNome = useId();
  const conhecida = ORDEM.includes(loja.fase);
  const contacto = contactoDaLoja(loja);
  const ultimoContacto = linhaUltimoContacto(loja);

  return (
    <section
      role="dialog"
      aria-labelledby={idNome}
      className="relative z-[2] shrink-0 overflow-y-auto border-t bg-card px-4 pt-3 pb-[max(14px,env(safe-area-inset-bottom))] md:px-6"
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
        <p className="mb-3 mt-1 text-sm text-muted-foreground" data-testid="crm-cartao-ultimo-contacto">
          {ultimoContacto.rotulo && <strong className="font-semibold text-foreground">{ultimoContacto.rotulo}</strong>}
          {ultimoContacto.rotulo && ' '}
          {ultimoContacto.texto}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" className="h-11 flex-1 basis-36">
            <Link to={`${base}/lojas/${encodeURIComponent(loja.id)}`}>
              <FileText className="h-4 w-4" aria-hidden="true" />
              Ver ficha
            </Link>
          </Button>
          <Button
            ref={refAdicionar}
            type="button"
            variant="outline"
            className="h-11 flex-1 basis-36"
            onClick={() => aoAdicionarARota?.(loja)}
            data-testid="crm-cartao-adicionar-rota"
          >
            <IconeRota className="h-4 w-4" aria-hidden="true" />
            {TITULO_ADICIONAR_A_ROTA}
          </Button>
        </div>
      </div>
    </section>
  );
}
