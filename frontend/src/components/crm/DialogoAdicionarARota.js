// "Adicionar à rota" a partir do cartão de uma loja no mapa (plano F3 T3.40; desenho original §6.1: "Adicionar à
// rota (escolhe o dia)"). Um `Dialog` do Radix, modal e por cima do mapa (o resto da página fica inerte), com os
// atalhos dos dias que já têm rota, o campo da data, o motivo (pré-escolhido pela fase), "Adicionar" e "Cancelar".
// As regras estão em `lib/crm/adicionarARota.js` (o controlador, com testes): este componente cria-o quando o
// diálogo abre (e o `destruir()` quando fecha: as respostas atrasadas e a rede já não mudam nada), desenha a
// `vista` que ele entrega e passa-lhe o que a pessoa faz.
//  - A abrir, a lista das rotas ("A carregar as rotas…"); se falhar, a mensagem e "Tentar novamente".
//  - O campo da data tem o `min` (o hoje do servidor) e o `max` (hoje + 365). Um dia passado escrito à mão não se
//    recusa aqui (`noValidate`): o servidor dá o 409 com a mensagem dele, por cima dos botões.
//  - Enquanto grava ("A adicionar…"), os campos e os botões ficam desligados e o diálogo não fecha (o "Cancelar",
//    o Escape e o toque fora ignoram-se: `podeFechar`). Se a gravação falhar e o foco se tiver perdido (o botão
//    desligado), volta a "Adicionar"; o 422 do dia ou do motivo fica junto do campo, com o foco lá.
//  - Com sucesso, o diálogo fecha e o toast diz o dia e as paragens, com "Abrir rota" (a rota desse dia).
//  - O foco vai para o título ao abrir e, ao fechar, para onde a página disser (`focarAoFechar`: o botão do
//    cartão). Sem o "×" do `DialogContent` do shadcn (pequeno e em inglês): fecha-se no "Cancelar".
// O nome da loja e as mensagens entram como texto (o React escapa-os).
import React, {
  useEffect, useId, useLayoutEffect, useRef, useState,
} from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { toast } from 'sonner';
import { Loader2, Route as IconeRota } from 'lucide-react'; // nunca `Route`: confundia-se com o do React Router
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import {
  Dialog, DialogDescription, DialogOverlay, DialogPortal, DialogTitle,
} from '../ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../ui/select';
import { adicionarParagem, listarRotas } from '../../lib/crm/api';
import {
  TEXTO_AJUDA_DIA,
  TEXTO_A_ADICIONAR,
  TEXTO_A_CARREGAR_DIAS,
  TEXTO_CANCELAR,
  TEXTO_DIA,
  TEXTO_DIAS_COM_ROTA,
  TEXTO_MOTIVO,
  TEXTO_TENTAR_DE_NOVO,
  criarAdicionarARota,
  podeFechar,
} from '../../lib/crm/adicionarARota';
import { criarEstadoRede } from '../../lib/crm/rede';
import './crm.css';

const API = Object.freeze({
  listarRotas: () => listarRotas(),
  adicionarParagem: (data, corpo) => adicionarParagem(data, corpo),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const CLASSE_INVALIDO = 'aria-[invalid=true]:border-destructive';

// Os ids de quem descreve um campo (o erro e a ajuda), só os que existem.
const descritoPor = (...ids) => ids.filter(Boolean).join(' ') || undefined;

// O conteúdo do diálogo aberto para uma loja (a `key` da loja: outra loja, outro controlador).
function Conteudo({
  loja, base, navegar, aoFechar, focarAoFechar,
}) {
  const idAtalhos = useId();
  const idData = useId();
  const idErroData = `${idData}-erro`;
  const idAjudaData = `${idData}-ajuda`;
  const idMotivo = useId();
  const idErroMotivo = `${idMotivo}-erro`;
  const conteudo = useRef(null);
  const titulo = useRef(null);
  const campoData = useRef(null);
  const campoMotivo = useRef(null);
  const botaoAdicionar = useRef(null);
  // A loja de quando o diálogo abriu (o controlador só a lê ao nascer).
  const [lojaDoDialogo] = useState(loja);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o controlador existir: a de um acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarAdicionarARota({ loja }).vista);
  // O campo que o controlador pediu para focar (o 422), depois de o React mostrar o erro.
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

  // As funções mais recentes da página (o toast e o "Abrir rota" podem chegar depois de várias mudanças).
  const pagina = useRef({ navegar, aoFechar });
  useLayoutEffect(() => {
    pagina.current = { navegar, aoFechar };
  });

  // Depois do `destruir()` o controlador já não chama nada (nem a vista, nem o aviso, nem o foco).
  useEffect(() => {
    const criado = criarAdicionarARota({
      api: API,
      loja: lojaDoDialogo,
      rede: REDE,
      base,
      navegar: (caminho) => pagina.current.navegar?.(caminho),
      aoMudarVista: setVista,
      aoAvisar: (texto, opcoes) => {
        toast.success(texto, { action: { label: opcoes.acao, onClick: () => opcoes.abrir() } });
        pagina.current.aoFechar?.();
      },
      aoFocar: (alvo) => {
        focoPendente.current = alvo;
        setPedidosDeFoco((n) => n + 1);
      },
    });
    setEcra(criado);
    criado.iniciar(); // mostra logo a vista "a carregar" deste controlador
    return () => criado.destruir();
  }, [lojaDoDialogo, base]);

  // O 422 do dia ou do motivo: o foco vai para o campo, já com o erro por baixo.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    if (alvo === 'data') campoData.current?.focus();
    else if (alvo === 'motivo') campoMotivo.current?.focus();
  }, [pedidosDeFoco, vista]);

  // A gravação acabou com um erro (com sucesso o diálogo fecha): se o foco se perdeu com os botões desligados (o
  // toque em "Adicionar", o Enter no campo da data) — saiu do diálogo, ou o Radix guardou-o no próprio diálogo —,
  // volta a "Adicionar".
  const aGravar = vista.camposDesativados;
  const gravava = useRef(false);
  useLayoutEffect(() => {
    const acabou = gravava.current && !aGravar;
    gravava.current = aGravar;
    if (!acabou) return;
    const foco = document.activeElement;
    if (foco === conteudo.current || !conteudo.current?.contains(foco)) botaoAdicionar.current?.focus();
  }, [aGravar]);

  // O Escape e o toque fora não fecham enquanto grava. O Radix pode chamar uma versão antiga desta função (o
  // ouvinte do Escape fica com a do primeiro desenho), por isso lê a vista mais recente de um `ref`.
  const vistaAtual = useRef(vista);
  useLayoutEffect(() => {
    vistaAtual.current = vista;
  });
  const reterSeGrava = (evento) => {
    if (!podeFechar(vistaAtual.current)) evento.preventDefault();
  };

  const {
    estado, falha, adicionar,
  } = vista;
  const pronto = estado === 'pronto';

  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        ref={conteudo}
        className="fixed left-1/2 top-1/2 z-50 grid max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-2xl border bg-background p-5 shadow-lg sm:p-6"
        onOpenAutoFocus={(evento) => {
          evento.preventDefault();
          titulo.current?.focus();
        }}
        onCloseAutoFocus={(evento) => {
          evento.preventDefault();
          focarAoFechar?.();
        }}
        onEscapeKeyDown={reterSeGrava}
        onInteractOutside={reterSeGrava}
        aria-busy={aGravar ? 'true' : undefined}
        data-testid="crm-dialogo-adicionar-rota"
      >
        <div className="grid gap-1">
          <DialogTitle
            ref={titulo}
            tabIndex={-1}
            className="rounded-sm font-heading text-lg font-bold leading-snug focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {vista.titulo}
          </DialogTitle>
          <DialogDescription className="text-sm font-semibold text-muted-foreground [overflow-wrap:anywhere]">
            {vista.loja.nome}
          </DialogDescription>
        </div>

        {/* noValidate: um dia fora do `min`/`max` vai ao servidor, que responde com a mensagem dele (pt-PT). */}
        <form
          noValidate
          className="grid min-w-0 gap-4"
          onSubmit={(evento) => {
            evento.preventDefault();
            ecra?.adicionar();
          }}
        >
          {estado === 'a_carregar' && (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="crm-adicionar-rota-a-carregar">
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              {TEXTO_A_CARREGAR_DIAS}
            </p>
          )}

          {estado === 'falha' && (
            <div className="grid justify-items-start gap-3">
              <p role="alert" className="text-sm font-medium text-destructive [overflow-wrap:anywhere]" data-testid="crm-adicionar-rota-falha">
                {falha.mensagem}
              </p>
              <Button type="button" variant="outline" className="h-11" onClick={() => ecra?.tentarDeNovo()} disabled={falha.aTentar}>
                {TEXTO_TENTAR_DE_NOVO}
              </Button>
            </div>
          )}

          {pronto && (
            // Enquanto grava, os atalhos, a data e o motivo ficam desligados.
            <fieldset disabled={aGravar} className="m-0 grid min-w-0 gap-4 border-0 p-0">
              {vista.atalhos.length > 0 && (
                <div role="group" aria-labelledby={idAtalhos} className="grid gap-1.5">
                  <p id={idAtalhos} className="text-sm font-medium">{TEXTO_DIAS_COM_ROTA}</p>
                  <div className="flex flex-wrap gap-2" data-testid="crm-adicionar-rota-atalhos">
                    {vista.atalhos.map((atalho) => (
                      <Button
                        key={atalho.data}
                        type="button"
                        variant={atalho.escolhido ? 'default' : 'outline'}
                        aria-pressed={atalho.escolhido}
                        className="h-auto min-h-11 whitespace-normal py-2 text-left"
                        onClick={() => ecra?.escolherDia(atalho.data)}
                      >
                        {atalho.texto}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid gap-1.5">
                <Label htmlFor={idData}>{TEXTO_DIA}</Label>
                <Input
                  id={idData}
                  ref={campoData}
                  type="date"
                  value={vista.data}
                  min={vista.min}
                  max={vista.max}
                  onChange={(evento) => ecra?.escolherDia(evento.target.value)}
                  className={`h-11 ${CLASSE_INVALIDO}`}
                  aria-invalid={vista.erroData ? 'true' : undefined}
                  aria-describedby={descritoPor(vista.erroData && idErroData, idAjudaData)}
                  data-testid="crm-adicionar-rota-data"
                />
                {vista.erroData && (
                  <p id={idErroData} className="text-sm font-medium text-destructive [overflow-wrap:anywhere]">{vista.erroData}</p>
                )}
                <p id={idAjudaData} className="text-sm text-muted-foreground">{TEXTO_AJUDA_DIA}</p>
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor={idMotivo}>{TEXTO_MOTIVO}</Label>
                <Select
                  value={vista.motivo}
                  disabled={aGravar}
                  onValueChange={(motivo) => ecra?.mudarMotivo(motivo)}
                >
                  <SelectTrigger
                    id={idMotivo}
                    ref={campoMotivo}
                    className={`h-11 ${CLASSE_INVALIDO}`}
                    aria-invalid={vista.erroMotivo ? 'true' : undefined}
                    aria-describedby={descritoPor(vista.erroMotivo && idErroMotivo)}
                    data-testid="crm-adicionar-rota-motivo"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {vista.opcoesMotivo.map((opcao) => (
                      <SelectItem key={opcao.valor} value={opcao.valor} className="min-h-11">
                        {opcao.texto}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {vista.erroMotivo && (
                  <p id={idErroMotivo} className="text-sm font-medium text-destructive [overflow-wrap:anywhere]">{vista.erroMotivo}</p>
                )}
              </div>
            </fieldset>
          )}

          <div className="grid gap-2 border-t pt-4">
            {vista.alerta && (
              <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-adicionar-rota-alerta">
                {vista.alerta}
              </p>
            )}
            {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
            <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="crm-adicionar-rota-falta">
              {adicionar.falta ?? ''}
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="outline"
                className="h-11"
                disabled={!podeFechar(vista)}
                onClick={() => aoFechar?.()}
                data-testid="crm-adicionar-rota-cancelar"
              >
                {TEXTO_CANCELAR}
              </Button>
              {pronto && (
                <Button
                  ref={botaoAdicionar}
                  type="submit"
                  className="h-11"
                  disabled={!adicionar.ativo}
                  data-testid="crm-adicionar-rota-adicionar"
                >
                  {adicionar.texto === TEXTO_A_ADICIONAR
                    ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                    : <IconeRota aria-hidden="true" />}
                  {adicionar.texto}
                </Button>
              )}
            </div>
          </div>
        </form>
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

// loja: a loja do cartão ({id, nome, fase}), ou null com o diálogo fechado. base: a casa do CRM (`/crm` ou
// `/admin/crm`); navegar(caminho): o `navigate` do React Router (o "Abrir rota" do toast). aoFechar(): a página
// fecha o diálogo ("Cancelar", o Escape, o toque fora, ou a paragem gravada). focarAoFechar(): para onde vai o
// foco quando o diálogo fecha.
export default function DialogoAdicionarARota({
  loja, base, navegar, aoFechar, focarAoFechar,
}) {
  const aberto = loja != null;
  return (
    <Dialog
      open={aberto}
      onOpenChange={(abrir) => {
        if (!abrir) aoFechar?.();
      }}
    >
      {aberto && (
        <Conteudo
          key={loja.id}
          loja={loja}
          base={base}
          navegar={navegar}
          aoFechar={aoFechar}
          focarAoFechar={focarAoFechar}
        />
      )}
    </Dialog>
  );
}
