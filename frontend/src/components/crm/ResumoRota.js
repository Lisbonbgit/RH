// O resumo da rota no painel do planeador (plano F3 T3.38; pages/crm/CrmRota.js). Só desenha a `vista` do
// planeador (`lib/crm/planeador.js`) com as regras do `lib/crm/painelRota.js` e avisa a página do que a
// pessoa fez; quem grava é o planeador.
//  - O estado da rota ("Rascunho", "Planeada", "Concluída", "Ainda sem paragens") e quantas paragens leva
//    ("6 de 48 paragens"; fora da leitura só).
//  - Os totais do último cálculo (distância, condução e regresso previsto, a vermelho depois do limite),
//    esbatidos quando as horas não são as atuais, com o rótulo das horas ("Horas antigas — Recalcular
//    horas", "a recalcular", "sem horas — ordene à mão").
//  - Os avisos da rota inteira (o regresso tarde, as fechadas neste dia, as que não cabem).
//  - Os botões "Calcular melhor ordem", "Recalcular horas" e "Guardar rota", desligados com o motivo por
//    baixo (cada motivo uma vez; o botão aponta-lhe com `aria-describedby`), e a mensagem do último cálculo
//    que falhou. Com paragens que não cabem, o "Guardar rota" pergunta primeiro num `AlertDialog` ("N paragens
//    não cabem — guardar mesmo assim?"; o foco na escolha que não grava e de volta ao botão).
//  - Os blocos de 9 paragens para o Google Maps, como ligações tocadas pela pessoa: só pelo `hrefNavegacao`
//    (regra 9 do §0) e noutro separador com `rel="noopener noreferrer"`.
// Em leitura só não há botões.
//
// `RodapeOrs` é o bloco próprio da atribuição do openrouteservice, no fim do painel (nunca sobre o mapa nem
// junto da atribuição da Google; correções do mapa Google, T3.38): a frase `TEXTO_ROTA_DE_TERCEIROS` e, por
// baixo, a atribuição exata desenhada a partir das `partes` (o `Partes`, com as ligações das constantes).
// Fica preso ao fundo do painel enquanto ele desloca (`sticky`, dentro do painel: o painel nunca está por
// cima do mapa), para estar sempre à vista no ecrã do planeador (§1 "Atribuição do ORS").
//
// Os textos dos dados entram como texto (o React escapa-os).
import React, { useId, useRef } from 'react';
import { ExternalLink, ListOrdered, Loader2, RefreshCw, Save } from 'lucide-react';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from '../ui/alert-dialog';
import { Partes } from './Partes';
import { hrefNavegacao } from '../../lib/crm/dom';
import {
  TEXTO_CANCELAR,
  TEXTO_GUARDAR_MESMO_ASSIM,
  TEXTO_GUARDAR_NAO_CABEM,
  TITULO_ATRIBUICAO_ORS,
  TITULO_BLOCOS_GOOGLE,
  TITULO_RESUMO,
  botoesDoResumo,
  totaisDoResumo,
} from '../../lib/crm/painelRota';
import { TEXTO_A_CALCULAR, TEXTO_A_RECALCULAR } from '../../lib/crm/planeador';

const ICONES = { calcular: ListOrdered, recalcular: RefreshCw, guardar: Save };
const VARIANTES = { calcular: 'outline', recalcular: 'outline', guardar: 'default' };
const EM_CURSO = [TEXTO_A_CALCULAR, TEXTO_A_RECALCULAR];

function Totais({ totais, horas }) {
  if (totais === null && !horas) return null;
  return (
    <div className="grid gap-1">
      {totais && (
        <dl className={`grid grid-cols-3 gap-2 ${totais.antigos ? 'opacity-60' : ''}`} data-testid="crm-rota-totais">
          {totais.itens.map((item) => (
            <div key={item.chave} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{item.rotulo}</dt>
              <dd className={`font-semibold tabular-nums ${item.aviso ? 'text-destructive' : ''}`}>{item.valor}</dd>
            </div>
          ))}
        </dl>
      )}
      {horas && <p className="text-sm text-muted-foreground" data-testid="crm-rota-horas">{horas}</p>}
    </div>
  );
}

function Botoes({ resumo, pergunta, acoes }) {
  const idMotivos = useId();
  const botaoGuardar = useRef(null);
  const primeiraEscolha = useRef(null);
  const aoTocar = { calcular: acoes.aoCalcular, recalcular: acoes.aoRecalcular, guardar: acoes.aoGuardar };

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        {resumo.botoes.map((botao) => {
          const Icone = EM_CURSO.includes(botao.texto) ? Loader2 : ICONES[botao.chave];
          return (
            <Button
              key={botao.chave}
              ref={botao.chave === 'guardar' ? botaoGuardar : undefined}
              type="button"
              variant={VARIANTES[botao.chave]}
              className="h-auto min-h-11 flex-1 whitespace-normal py-2"
              disabled={!botao.ativo}
              aria-describedby={botao.motivo === null ? undefined : `${idMotivos}-${botao.motivo}`}
              onClick={() => aoTocar[botao.chave]?.()}
              data-testid={`crm-rota-${botao.chave}`}
            >
              <Icone className={Icone === Loader2 ? 'animate-spin motion-reduce:animate-none' : undefined} aria-hidden="true" />
              {botao.texto}
            </Button>
          );
        })}
      </div>
      {resumo.motivos.length > 0 && (
        <ul className="grid gap-0.5 text-sm text-muted-foreground" data-testid="crm-rota-motivos">
          {resumo.motivos.map((motivo, i) => (
            <li key={motivo} id={`${idMotivos}-${i}`}>
              {motivo}
            </li>
          ))}
        </ul>
      )}
      {resumo.mensagem && (
        <p role="status" className="text-sm font-medium text-destructive" data-testid="crm-rota-mensagem-calculo">
          {resumo.mensagem}
        </p>
      )}

      <AlertDialog
        open={pergunta !== null}
        onOpenChange={(abrir) => {
          if (!abrir) acoes.aoResponderGuardar?.(false);
        }}
      >
        {pergunta !== null && (
          <AlertDialogContent
            className="w-[calc(100%-2rem)] max-w-[26rem] rounded-2xl"
            onOpenAutoFocus={(evento) => {
              // O foco vai para a primeira escolha: a que não grava.
              evento.preventDefault();
              primeiraEscolha.current?.focus();
            }}
            onCloseAutoFocus={(evento) => {
              evento.preventDefault();
              botaoGuardar.current?.focus();
            }}
            data-testid="crm-dialogo-guardar"
          >
            <AlertDialogTitle className="text-base font-semibold">{pergunta}</AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-muted-foreground">{TEXTO_GUARDAR_NAO_CABEM}</AlertDialogDescription>
            <div className="flex flex-col gap-2">
              <Button
                ref={primeiraEscolha}
                type="button"
                variant="outline"
                className="h-auto min-h-11 w-full whitespace-normal py-2"
                onClick={() => acoes.aoResponderGuardar?.(false)}
              >
                {TEXTO_CANCELAR}
              </Button>
              <Button
                type="button"
                className="h-auto min-h-11 w-full whitespace-normal py-2"
                onClick={() => acoes.aoResponderGuardar?.(true)}
              >
                {TEXTO_GUARDAR_MESMO_ASSIM}
              </Button>
            </div>
          </AlertDialogContent>
        )}
      </AlertDialog>
    </div>
  );
}

function BlocosGoogle({ blocos }) {
  const idTitulo = useId();
  if (blocos.length === 0) return null;
  return (
    <section aria-labelledby={idTitulo} className="grid gap-1">
      <h3 id={idTitulo} className="text-sm font-semibold">{TITULO_BLOCOS_GOOGLE}</h3>
      <ul className="grid gap-1">
        {blocos.map((bloco) => (
          <li key={bloco.rotulo}>
            <a
              href={hrefNavegacao(bloco.href)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-primary underline-offset-2 hover:underline"
              data-testid="crm-rota-bloco-google"
            >
              {bloco.rotulo}
              <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function ResumoRota({
  vista, aoCalcular, aoRecalcular, aoGuardar, aoResponderGuardar,
}) {
  const idTitulo = useId();
  const totais = totaisDoResumo(vista.totais);
  const botoes = botoesDoResumo(vista.acoes, vista.calculo);
  const pergunta = vista.acoes?.guardar?.pergunta ?? null;

  return (
    <section aria-labelledby={idTitulo} className="grid gap-3 rounded-2xl border bg-card p-4" data-testid="crm-resumo-rota">
      <h2 id={idTitulo} className="sr-only">{TITULO_RESUMO}</h2>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {vista.rotuloEstado && <Badge variant="secondary" data-testid="crm-rota-estado">{vista.rotuloEstado}</Badge>}
        {!vista.somenteLeitura && vista.limite && (
          <span className="text-sm text-muted-foreground" data-testid="crm-rota-limite">{vista.limite.texto}</span>
        )}
      </div>
      <Totais totais={totais} horas={vista.horas?.texto ?? null} />
      {vista.avisos.length > 0 && (
        <ul className="grid gap-1 text-sm font-medium text-amber-700 dark:text-amber-400" data-testid="crm-rota-avisos">
          {vista.avisos.map((aviso) => (
            <li key={aviso}>{aviso}</li>
          ))}
        </ul>
      )}
      {botoes && (
        <Botoes resumo={botoes} pergunta={pergunta} acoes={{ aoCalcular, aoRecalcular, aoGuardar, aoResponderGuardar }} />
      )}
      <BlocosGoogle blocos={vista.blocosGoogle} />
    </section>
  );
}

// O bloco da atribuição do openrouteservice (`vista.atribuicaoOrs`: {aviso, texto, partes}).
export function RodapeOrs({ atribuicao }) {
  const idTitulo = useId();
  if (!atribuicao) return null;
  return (
    <section
      aria-labelledby={idTitulo}
      className="sticky bottom-0 grid gap-0.5 border-t bg-card px-4 py-3 text-xs text-muted-foreground"
      data-testid="crm-atribuicao-ors"
    >
      <h2 id={idTitulo} className="font-semibold text-foreground">{TITULO_ATRIBUICAO_ORS}</h2>
      <p data-testid="crm-atribuicao-ors-aviso">{atribuicao.aviso}</p>
      <p data-testid="crm-atribuicao-ors-texto">
        <Partes partes={atribuicao.partes} />
      </p>
    </section>
  );
}
