// As definições do dia no painel do planeador (plano F3 T3.39; desenho original §7.1, passo 5): a hora de saída,
// a hora limite de regresso, o início e o fim da rota e "Evitar portagens". Só desenha a `vista` do planeador
// (`vista.definicoes` e `vista.escolherPonto`, pelo `definicoesDoPainel` do `lib/crm/painelRota.js`) e avisa a
// página do que a pessoa fez; quem grava é o planeador (cada mudança grava logo, §1 "Gravação").
//  - Fechadas por omissão (Radix `Collapsible`), com o resumo de uma linha no botão ("Saída 08:00 · Regresso até
//    19:00 · Início e fim: Fábrica"): a lista das paragens fica perto do topo do painel.
//  - As horas (`<input type="time">`) gravam ao sair do campo ou com Enter, só se mudaram (e nunca o mesmo texto
//    duas vezes seguidas: o 422 já disse porquê); seguem a resposta do servidor (a visão otimista desfeita
//    volta ao valor de antes).
//  - O início e o fim: "Fábrica" (`aoUsarFabrica`) ou "Ponto no mapa" (`aoEscolherPonto`: a página mostra a
//    faixa "Toque no mapa no ponto de início" por cima do mapa, com "Cancelar"; tocar outra vez no botão também
//    cancela). O botão da escolha em vigor (ou à espera do toque) fica premido (`aria-pressed`). Sem mapa onde
//    tocar (sem a chave Google, ou a Google que falhou), "Ponto no mapa" desliga-se com "Sem mapa — use a
//    fábrica." por baixo (`aria-describedby`; revisão dos ecrãs da F3, F3-UX-6).
//  - "Evitar portagens" é um `Switch` (o rótulo inteiro é a área de toque, ≥ 44 px), com a nota de que a melhor
//    ordem se escolhe com portagens (desenho original §7.2).
//  - Desligadas sem rede, no conflito e numa rota virtual (a mensagem "Adicione a primeira paragem para mudar as
//    definições do dia."; correções "T3.31 / T3.39" e "T3.20 / T3.31 / T3.39"). Em leitura só, só o resumo.
// Os valores entram como texto (o React escapa-os).
import React, { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Settings2 } from 'lucide-react';
import { Button } from '../ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../ui/collapsible';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Switch } from '../ui/switch';
import {
  TEXTO_EVITAR_PORTAGENS, TEXTO_NOTA_PORTAGENS, TITULO_DEFINICOES, definicoesDoPainel, faixaDoPonto,
} from '../../lib/crm/painelRota';
import { TEXTO_FABRICA, TEXTO_PONTO_NO_MAPA } from '../../lib/crm/planeador';

// Uma hora do dia: escreve-se à vontade e grava ao sair do campo ou com Enter (o valor que já está, o planeador
// não o grava).
function CampoHora({ id, hora, ativas, aoMudarDefinicao }) {
  const [rascunho, setRascunho] = useState(hora.valor);
  const enviado = useRef(null);

  useEffect(() => {
    setRascunho(hora.valor);
    enviado.current = null;
  }, [hora.valor]);

  function confirmar() {
    if (rascunho === enviado.current) return;
    enviado.current = rascunho;
    aoMudarDefinicao?.(hora.chave, rascunho);
  }

  return (
    <div className="grid min-w-0 gap-1.5">
      <Label htmlFor={id}>{hora.rotulo}</Label>
      <Input
        id={id}
        type="time"
        step={60}
        className="h-11"
        value={rascunho}
        disabled={!ativas}
        onChange={(evento) => setRascunho(evento.target.value)}
        onBlur={confirmar}
        onKeyDown={(evento) => {
          if (evento.key === 'Enter') {
            evento.preventDefault();
            confirmar();
          }
        }}
        data-testid={`crm-definicao-${hora.chave}`}
      />
    </div>
  );
}

// O início ou o fim: "Fábrica" ou "Ponto no mapa" (`pontoNoMapa`: {ativo, falta}, e o id do porquê).
function EscolhaDaPonta({
  id, ponta, ativas, pontoNoMapa, idFaltaMapa, aoUsarFabrica, aoEscolherPonto,
}) {
  const naFabrica = ponta.fabrica && !ponta.aEscolher;
  const noMapa = ponta.noMapa || ponta.aEscolher;
  const faixa = ponta.aEscolher ? faixaDoPonto(ponta.chave) : null;
  return (
    <div className="grid gap-1.5" data-testid={`crm-definicao-${ponta.chave}`}>
      <span id={id} className="text-sm font-medium leading-none">{ponta.rotulo}</span>
      <div role="group" aria-labelledby={id} className="grid grid-cols-2 gap-2">
        <Button
          type="button"
          variant={naFabrica ? 'default' : 'outline'}
          className="h-auto min-h-11 whitespace-normal py-2"
          aria-pressed={naFabrica}
          disabled={!ativas}
          onClick={() => aoUsarFabrica?.(ponta.chave)}
        >
          {TEXTO_FABRICA}
        </Button>
        <Button
          type="button"
          variant={noMapa ? 'default' : 'outline'}
          className="h-auto min-h-11 whitespace-normal py-2"
          aria-pressed={noMapa}
          aria-describedby={pontoNoMapa.falta ? idFaltaMapa : undefined}
          disabled={!pontoNoMapa.ativo}
          onClick={() => aoEscolherPonto?.(ponta.aEscolher ? null : ponta.chave)}
        >
          {TEXTO_PONTO_NO_MAPA}
        </Button>
      </div>
      {faixa && <p className="text-sm font-medium text-primary">{faixa.texto}</p>}
    </div>
  );
}

// definicoes, escolherPonto: os da vista; somenteLeitura: só o resumo.
// aoMudarDefinicao(chave, valor), aoUsarFabrica(ponta), aoEscolherPonto(ponta | null): as ações do planeador.
export default function DefinicoesDoDia({
  definicoes, escolherPonto, somenteLeitura, aoMudarDefinicao, aoUsarFabrica, aoEscolherPonto,
}) {
  const idBase = useId();
  const [aberta, setAberta] = useState(false);
  const painel = definicoesDoPainel(definicoes, escolherPonto);
  if (painel === null) return null;

  if (somenteLeitura) {
    return (
      <section aria-labelledby={`${idBase}-titulo`} className="grid gap-1 rounded-2xl border bg-card px-4 py-3" data-testid="crm-definicoes-dia">
        <h2 id={`${idBase}-titulo`} className="font-heading text-base font-bold">{TITULO_DEFINICOES}</h2>
        <p className="text-sm text-muted-foreground" data-testid="crm-definicoes-resumo">{painel.resumo}</p>
      </section>
    );
  }

  return (
    <section aria-labelledby={`${idBase}-titulo`} className="rounded-2xl border bg-card" data-testid="crm-definicoes-dia">
      <Collapsible open={aberta} onOpenChange={setAberta}>
        <h2 id={`${idBase}-titulo`}>
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex min-h-11 w-full items-start gap-3 rounded-2xl px-4 py-3 text-left hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="crm-definicoes-abrir"
            >
              <Settings2 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="grid min-w-0 flex-1 gap-0.5">
                <span className="font-heading text-base font-bold">{TITULO_DEFINICOES}</span>
                <span className="text-sm font-normal text-muted-foreground" data-testid="crm-definicoes-resumo">{painel.resumo}</span>
              </span>
              <ChevronDown
                className={`mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform ${aberta ? 'rotate-180' : ''}`}
                aria-hidden="true"
              />
            </button>
          </CollapsibleTrigger>
        </h2>
        <CollapsibleContent>
          <div className="grid gap-4 px-4 pb-4">
            {painel.mensagem && (
              <p className="text-sm font-medium text-muted-foreground" data-testid="crm-definicoes-mensagem">{painel.mensagem}</p>
            )}
            <div className="grid grid-cols-2 gap-3">
              {painel.horas.map((hora) => (
                <CampoHora
                  key={hora.chave}
                  id={`${idBase}-${hora.chave}`}
                  hora={hora}
                  ativas={painel.ativas}
                  aoMudarDefinicao={aoMudarDefinicao}
                />
              ))}
            </div>
            {painel.pontas.map((ponta) => (
              <EscolhaDaPonta
                key={ponta.chave}
                id={`${idBase}-${ponta.chave}`}
                ponta={ponta}
                ativas={painel.ativas}
                pontoNoMapa={painel.pontoNoMapa}
                idFaltaMapa={`${idBase}-sem-mapa`}
                aoUsarFabrica={aoUsarFabrica}
                aoEscolherPonto={aoEscolherPonto}
              />
            ))}
            {painel.pontoNoMapa.falta && (
              <p id={`${idBase}-sem-mapa`} className="text-sm text-muted-foreground" data-testid="crm-definicoes-sem-mapa">
                {painel.pontoNoMapa.falta}
              </p>
            )}
            <div className="grid gap-1">
              <Label
                htmlFor={`${idBase}-portagens`}
                className="flex min-h-11 cursor-pointer items-center justify-between gap-3"
              >
                {TEXTO_EVITAR_PORTAGENS}
                <Switch
                  id={`${idBase}-portagens`}
                  checked={painel.evitarPortagens}
                  disabled={!painel.ativas}
                  onCheckedChange={(ligado) => aoMudarDefinicao?.('evitar_portagens', ligado)}
                  data-testid="crm-definicao-evitar_portagens"
                />
              </Label>
              <p className="text-xs text-muted-foreground">{TEXTO_NOTA_PORTAGENS}</p>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
