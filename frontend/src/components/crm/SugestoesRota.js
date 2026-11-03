// As sugestões "aproveitar a viagem" no painel do planeador (plano F3 T3.39; desenho original §7.1, passo 4) e o
// cartão pequeno de uma loja esbatida tocada no mapa. Só desenham a `vista` do planeador (`vista.sugestoes` com o
// `vista.podeAdicionar`, e `vista.lojaEscolhida`, pelo `sugestoesDoPainel`/`cartaoDaLoja` do
// `lib/crm/painelRota.js`) e avisam a página; quem grava é o planeador (adicionar não é otimista: "A adicionar…"
// até à resposta).
//  - `SugestoesRota`: os grupos do servidor (contactadas e depois potenciais, as mais perto primeiro), cada loja
//    com a distância ("1,2 km", "no caminho, 0,8 km") e "Adicionar"; "e mais N" no fim do grupo. A carregar, sem
//    paragens ("Adicione a primeira paragem pelo mapa."), sem nenhuma ou com a falha (e "Tentar novamente"), a
//    mensagem. Ao adicionar, a linha sai da lista: se o foco ficou perdido, vai para o "Adicionar" que ficou no
//    lugar dela (ou o último, ou o título).
//  - `CartaoLojaEscolhida`: o nome, a fase, o motivo (o da fase) e "Adicionar à rota", com "Fechar" (o Escape
//    também o fecha: trata-o a página). A página põe-no por baixo da área do mapa, fora dela (o mapa encolhe;
//    nada nosso o tapa).
// Os nomes entram como texto (o React escapa-os).
import React, { useEffect, useId, useRef } from 'react';
import { Loader2, Plus, Route as IconeRota, X } from 'lucide-react'; // nunca `Route`: confundia-se com o do React Router
import { Button } from '../ui/button';
import {
  TEXTO_FECHAR, TEXTO_TENTAR_DE_NOVO, cartaoDaLoja, sugestoesDoPainel,
} from '../../lib/crm/painelRota';
import { TEXTO_A_ADICIONAR } from '../../lib/crm/planeador';
import { ORDEM } from '../../lib/crm/fases';
import './crm.css';

const BOTAO_SUGESTAO = 'button[data-sugestao]';

// "A adicionar…" a rodar; senão o ícone do botão.
function IconeDoBotao({ texto, Icone }) {
  if (texto === TEXTO_A_ADICIONAR) return <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />;
  return <Icone aria-hidden="true" />;
}

// sugestoes, podeAdicionar: os da vista. aoAdicionar(lojaId), aoTentarDeNovo(): as ações do planeador.
export default function SugestoesRota({
  sugestoes, podeAdicionar, aoAdicionar, aoTentarDeNovo,
}) {
  const idBase = useId();
  const seccao = useRef(null);
  const titulo = useRef(null);
  // O "Adicionar" tocado ({id, indice}) até a resposta chegar: depois, se o foco se perdeu, devolve-se.
  const pendente = useRef(null);
  const painel = sugestoesDoPainel(sugestoes, podeAdicionar);
  const lojas = painel === null ? [] : painel.grupos.flatMap((grupo) => grupo.lojas);

  useEffect(() => {
    const tocado = pendente.current;
    if (tocado === null) return;
    const aindaLa = lojas.find((loja) => loja.id === tocado.id);
    if (aindaLa?.botao.texto === TEXTO_A_ADICIONAR) return;
    pendente.current = null;
    if (document.activeElement !== document.body) return;
    const botoes = seccao.current ? [...seccao.current.querySelectorAll(BOTAO_SUGESTAO)] : [];
    const alvo = botoes[Math.min(tocado.indice, botoes.length - 1)] ?? titulo.current;
    alvo?.focus();
  });

  if (painel === null) return null;

  function adicionar(loja) {
    pendente.current = { id: loja.id, indice: lojas.indexOf(loja) };
    aoAdicionar?.(loja.id);
  }

  return (
    <section ref={seccao} aria-labelledby={`${idBase}-titulo`} className="grid gap-3" data-testid="crm-sugestoes">
      <h2 ref={titulo} id={`${idBase}-titulo`} tabIndex={-1} className="font-heading text-base font-bold focus:outline-none">
        {painel.titulo}
      </h2>
      {painel.mensagem && (
        <p
          className={painel.estado === 'falha' ? 'text-sm font-medium text-destructive' : 'text-sm text-muted-foreground'}
          role={painel.estado === 'falha' ? 'alert' : undefined}
          data-testid="crm-sugestoes-mensagem"
        >
          {painel.mensagem}
        </p>
      )}
      {painel.tentar && (
        <Button
          type="button"
          variant="outline"
          className="h-11 w-fit"
          disabled={painel.aTentar}
          onClick={() => aoTentarDeNovo?.()}
          data-testid="crm-sugestoes-tentar"
        >
          {TEXTO_TENTAR_DE_NOVO}
        </Button>
      )}
      {painel.grupos.map((grupo, g) => (
        <section key={`${grupo.fase}-${g}`} aria-labelledby={`${idBase}-grupo-${g}`} className="grid gap-1.5" data-testid="crm-sugestoes-grupo">
          <h3 id={`${idBase}-grupo-${g}`} className="flex items-center gap-2 text-sm font-semibold">
            {ORDEM.includes(grupo.fase) && <span aria-hidden="true" className={`crm-amostra-fase pino--${grupo.fase}`} />}
            {grupo.titulo}
          </h3>
          {grupo.lojas.length > 0 && (
            <ul className="grid gap-1.5">
              {grupo.lojas.map((loja) => (
                <li key={loja.id} className="flex items-center gap-2 rounded-lg border bg-card py-1 pl-3 pr-1" data-testid="crm-sugestao">
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="font-medium leading-snug [overflow-wrap:anywhere]">{loja.nome}</span>
                    {loja.distancia && <span className="text-sm text-muted-foreground">{loja.distancia}</span>}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-11 shrink-0"
                    disabled={!loja.botao.ativo}
                    aria-label={loja.botao.rotulo}
                    onClick={() => adicionar(loja)}
                    data-sugestao={loja.id}
                  >
                    <IconeDoBotao texto={loja.botao.texto} Icone={Plus} />
                    {loja.botao.texto}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {grupo.textoMais && <p className="text-sm text-muted-foreground">{grupo.textoMais}</p>}
        </section>
      ))}
    </section>
  );
}

// loja: a `vista.lojaEscolhida`. aoAdicionar(lojaId, motivo), aoFechar(): as ações do planeador.
// refTitulo: o título, para a página lhe dar o foco quando o cartão abre.
export function CartaoLojaEscolhida({
  loja, aoAdicionar, aoFechar, refTitulo,
}) {
  const idTitulo = useId();
  const cartao = cartaoDaLoja(loja);
  if (cartao === null) return null;

  return (
    <section
      role="dialog"
      aria-labelledby={idTitulo}
      className="relative z-[2] shrink-0 border-t bg-card px-4 pt-2 pb-[max(12px,env(safe-area-inset-bottom))]"
      data-testid="crm-rota-cartao-loja"
    >
      <div className="flex items-start justify-between gap-3">
        <h2
          id={idTitulo}
          ref={refTitulo}
          tabIndex={-1}
          className="min-w-0 rounded-sm pt-2 font-heading text-base font-bold leading-snug [overflow-wrap:anywhere] focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {cartao.nome}
        </h2>
        <Button type="button" variant="ghost" className="h-11 shrink-0 gap-1.5" onClick={() => aoFechar?.()}>
          <X className="h-4 w-4" aria-hidden="true" />
          {TEXTO_FECHAR}
        </Button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="grid min-w-0 gap-0.5 text-sm text-muted-foreground">
          {cartao.rotuloFase && (
            <p className="flex items-center gap-2 font-semibold">
              <span aria-hidden="true" className={`crm-amostra-fase pino--${cartao.fase}`} />
              {cartao.rotuloFase}
            </p>
          )}
          <p>{cartao.textoMotivo}</p>
        </div>
        <Button
          type="button"
          className="h-11"
          disabled={!cartao.botao.ativo}
          onClick={() => aoAdicionar?.(cartao.id, cartao.motivo)}
          data-testid="crm-rota-cartao-adicionar"
        >
          <IconeDoBotao texto={cartao.botao.texto} Icone={IconeRota} />
          {cartao.botao.texto}
        </Button>
      </div>
    </section>
  );
}
