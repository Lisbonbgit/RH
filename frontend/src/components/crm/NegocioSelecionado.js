// O painel do negócio selecionado (plano do mapa Google, G13; adenda §6.3). Abre ao lado do mapa, nunca por
// cima dele, quando a pessoa toca no ícone de um negócio: os dados do negócio estão no balão da própria Google,
// dentro do mapa. Este painel só tem um texto fixo, a ação ("Adicionar como loja" no mapa, "Pôr o pino neste
// negócio" no seletor), o "Fechar" e, por baixo da ação, a dica de que o nome da loja se escreve à mão.
//
// Nenhum dado da Google entra aqui: o componente não recebe o identificador do lugar, nem nome, morada ou
// fotografia (as props são só estas cinco), por isso o texto do painel é o mesmo para qualquer negócio. A
// posição só se pede à Google quando a pessoa toca na ação (o `criarNegocioSelecionado` de
// `lib/crm/lugarGoogle.js`, por quem usa o painel); enquanto chega, o estado é `a_posicionar` e a ação fica
// desligada; se falhar, `erro`, com a mensagem num alerta, e a ação volta a ligar para tentar outra vez.
//
// {estado: 'aberto' | 'a_posicionar' | 'erro' | 'fechado', mensagem, acao: {texto, aoTocar}, aoFechar,
//  refTitulo}: a `refTitulo` fica no título (focável por código, tabIndex -1), para a página lhe pôr o foco ao
// abrir. Fechado, não desenha nada. A ação e o Fechar chamam-se sem argumentos.
import React, { useId } from 'react';
import { Loader2, X } from 'lucide-react';
import { Button } from '../ui/button';
import {
  ROTULO_NEGOCIO,
  TEXTO_A_POSICIONAR,
  TEXTO_ESCREVA_O_NOME,
  TEXTO_FECHAR_NEGOCIO,
  TEXTO_LUGAR_INDISPONIVEL,
  TEXTO_NEGOCIO_SELECIONADO,
} from '../../lib/crm/lugarGoogle';
import './crm.css';

const textoPreenchido = (valor) => typeof valor === 'string' && valor.trim() !== '';

export default function NegocioSelecionado({ estado, mensagem, acao, aoFechar, refTitulo }) {
  const idDica = useId();
  if (estado === 'fechado') return null;
  const aPosicionar = estado === 'a_posicionar';

  return (
    // Um <section> com nome já é uma região (o role explícito seria redundante: jsx-a11y/no-redundant-roles).
    <section className="crm-negocio" aria-label={ROTULO_NEGOCIO} data-estado={estado}>
      <div className="mx-auto max-w-2xl">
        <p
          ref={refTitulo}
          tabIndex={-1}
          className="rounded-sm font-heading text-base font-bold leading-snug focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {TEXTO_NEGOCIO_SELECIONADO}
        </p>
        {/* Sempre presente (vazio fora do a_posicionar), para os leitores de ecrã anunciarem a mudança. */}
        <p role="status" aria-live="polite" className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
          {aPosicionar && (
            <>
              <Loader2 className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              {TEXTO_A_POSICIONAR}
            </>
          )}
        </p>
        {estado === 'erro' && (
          <p role="alert" className="mt-1 text-sm font-medium text-destructive [overflow-wrap:anywhere]">
            {textoPreenchido(mensagem) ? mensagem : TEXTO_LUGAR_INDISPONIVEL}
          </p>
        )}
        <div className="crm-negocio__acoes">
          <Button
            type="button"
            className="h-11 flex-1 basis-48"
            disabled={aPosicionar}
            aria-describedby={idDica}
            onClick={() => acao.aoTocar()}
          >
            {acao.texto}
          </Button>
          <Button type="button" variant="outline" className="h-11 gap-1.5" onClick={() => aoFechar()}>
            <X className="h-4 w-4" aria-hidden="true" />
            {TEXTO_FECHAR_NEGOCIO}
          </Button>
        </div>
        <p id={idDica} className="crm-negocio__dica">
          {TEXTO_ESCREVA_O_NOME}
        </p>
      </div>
    </section>
  );
}
