// A secção "Contactos" da ficha da loja (desenho de 2026-11-07, §3): blocos numerados, do mais recente para o mais
// antigo, num cartão próprio, fora do formulário da ficha, com o seu próprio Guardar. As regras estão em
// `lib/crm/contactos.js` (com testes): este componente cria o ecrã num `useEffect`, desenha a `vista` que ele entrega
// e passa-lhe o que a pessoa faz.
//  - "Adicionar contacto" e "Corrigir" abrem o mesmo bloco, no topo da secção, não um diálogo: a data, o tipo (três
//    pastilhas) e o resumo. Enquanto grava, os campos ficam desativados e o texto fica lá.
//  - O porquê de Guardar estar desativado fica por baixo dele, num `aria-live`; sem rede, "Guardar — sem rede".
//  - Apagar pergunta num `AlertDialog`, com o foco na escolha que não apaga.
//  - O foco pedido pelo ecrã (`aoFocar`) vai para o nó com esse nome, depois de o React o mostrar. Um botão que já não
//    exista dá lugar a "Adicionar contacto".
// Com outra loja (a `key` do `lojaId` na ficha) tudo se cria de novo. Os dados entram como texto (o React escapa-os).
import React, {
  useEffect, useId, useLayoutEffect, useRef, useState,
} from 'react';
import { toast } from 'sonner';
import {
  Loader2, Pencil, Plus, Save, Trash2, WifiOff,
} from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Textarea } from '../ui/textarea';
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from '../ui/alert-dialog';
import {
  alterarContacto, apagarContacto, criarContacto, listarContactos,
} from '../../lib/crm/api';
import {
  ALVO_ADICIONAR, ALVO_GUARDAR, RESUMO_MAXIMO, ROTULO_DATA, ROTULO_RESUMO, ROTULO_TIPO, TEXTO_ADICIONAR_CONTACTO,
  TEXTO_APAGAR, TEXTO_A_CARREGAR_CONTACTOS, TEXTO_CANCELAR, TEXTO_CORRIGIDO, TEXTO_CORRIGIR, TEXTO_EXEMPLO_RESUMO,
  TEXTO_SEM_CONTACTOS, TEXTO_TENTAR_DE_NOVO, TITULO_CONTACTOS, alvoApagar, alvoCorrigir, criarContactos,
} from '../../lib/crm/contactos';
import { CLASSE_PASTILHA } from '../../lib/crm/formularioLoja';
import { novoUuid4 } from '../../lib/crm/ids';
import { TEXTO_A_GUARDAR, TEXTO_GUARDAR_SEM_REDE } from '../../lib/crm/lojaNova';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  listarContactos: (lojaId) => listarContactos(lojaId),
  criarContacto: (lojaId, corpo) => criarContacto(lojaId, corpo),
  alterarContacto: (lojaId, contactoId, corpo) => alterarContacto(lojaId, contactoId, corpo),
  apagarContacto: (lojaId, contactoId) => apagarContacto(lojaId, contactoId),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const VARIANTES_APAGAR = Object.freeze({ normal: 'outline', perigo: 'destructive' });
const CLASSE_ERRO = 'text-sm font-medium text-destructive [overflow-wrap:anywhere]';
const CLASSE_INVALIDO = 'aria-[invalid=true]:border-destructive';

// O bloco de escrever um contacto, novo ou a corrigir.
function BlocoContacto({
  bloco, guardarNo, ecra,
}) {
  const base = useId();
  const idTitulo = `${base}-titulo`;
  const idData = `${base}-data`;
  const idTipo = `${base}-tipo`;
  const idResumo = `${base}-resumo`;
  const idErro = (campo) => `${base}-${campo}-erro`;
  const { erros, guardar } = bloco;
  // Os atributos de erro de um campo: o erro por baixo, ligado a ele para o leitor de ecrã o ler com o campo.
  const comErro = (campo) => (erros[campo] ? { 'aria-invalid': 'true', 'aria-describedby': idErro(campo) } : {});
  const erro = (campo) => (erros[campo]
    ? <p id={idErro(campo)} className={CLASSE_ERRO} data-testid={`crm-contacto-erro-${campo}`}>{erros[campo]}</p>
    : null);

  let iconeGuardar = <Save aria-hidden="true" />;
  if (guardar.texto === TEXTO_A_GUARDAR) iconeGuardar = <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />;
  else if (guardar.texto === TEXTO_GUARDAR_SEM_REDE) iconeGuardar = <WifiOff aria-hidden="true" />;

  return (
    // noValidate: as mensagens dos campos são as do servidor (pt-PT), não as do browser.
    <form
      noValidate
      aria-labelledby={idTitulo}
      className="space-y-4 rounded-xl border bg-background p-4"
      onSubmit={(evento) => {
        evento.preventDefault();
        ecra?.guardar();
      }}
      data-testid="crm-contacto-bloco"
    >
      <h3 id={idTitulo} className="font-semibold">{bloco.titulo}</h3>
      {/* Enquanto grava, os campos ficam desativados; o que se escreveu fica lá. */}
      <fieldset disabled={bloco.camposDesativados} className="m-0 min-w-0 space-y-4 border-0 p-0">
        <div className="space-y-1.5">
          <Label htmlFor={idData}>{ROTULO_DATA}</Label>
          <Input
            id={idData}
            ref={guardarNo('data')}
            type="date"
            value={bloco.data ?? ''}
            min={bloco.min}
            max={bloco.max ?? undefined}
            onChange={(evento) => ecra?.mudarCampo('data', evento.target.value)}
            className={`h-11 ${CLASSE_INVALIDO}`}
            data-testid="crm-contacto-data"
            {...comErro('data')}
          />
          {erro('data')}
        </div>

        <fieldset className="m-0 min-w-0 space-y-2 border-0 p-0" {...comErro('tipo')} data-testid="crm-contacto-tipo">
          <legend className="mb-1.5 p-0 text-sm font-medium">{ROTULO_TIPO}</legend>
          <div className="flex flex-wrap gap-2">
            {bloco.opcoesTipo.map(({ valor, rotulo }) => (
              // O rótulo envolve a opção: a pastilha inteira (44 px) é área de toque.
              <label key={valor} htmlFor={`${idTipo}-${valor}`} className={CLASSE_PASTILHA}>
                <input
                  type="radio"
                  id={`${idTipo}-${valor}`}
                  name={idTipo}
                  value={valor}
                  ref={bloco.tipo === valor ? guardarNo('tipo') : undefined}
                  checked={bloco.tipo === valor}
                  onChange={() => ecra?.mudarCampo('tipo', valor)}
                  className="h-[18px] w-[18px] shrink-0 accent-primary"
                />
                {rotulo}
              </label>
            ))}
          </div>
          {erro('tipo')}
        </fieldset>

        <div className="space-y-1.5">
          <Label htmlFor={idResumo}>
            {ROTULO_RESUMO}
            <span aria-hidden="true" className="text-destructive"> *</span>
          </Label>
          <Textarea
            id={idResumo}
            ref={guardarNo('resumo')}
            rows={3}
            required
            maxLength={RESUMO_MAXIMO}
            placeholder={TEXTO_EXEMPLO_RESUMO}
            value={bloco.resumo}
            onChange={(evento) => ecra?.mudarCampo('resumo', evento.target.value)}
            className={`text-base md:text-sm ${CLASSE_INVALIDO}`}
            data-testid="crm-contacto-resumo"
            {...comErro('resumo')}
          />
          {erro('resumo')}
        </div>
      </fieldset>

      <div className="space-y-2">
        {bloco.alerta && (
          <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-contacto-alerta">
            {bloco.alerta}
          </p>
        )}
        {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
        <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="crm-contacto-falta">
          {guardar.falta ?? ''}
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="outline"
            className="h-11"
            disabled={bloco.camposDesativados}
            onClick={() => ecra?.cancelar()}
            data-testid="crm-contacto-cancelar"
          >
            {TEXTO_CANCELAR}
          </Button>
          <Button
            ref={guardarNo(ALVO_GUARDAR)}
            type="submit"
            className="h-11"
            disabled={!guardar.ativo}
            data-testid="crm-contacto-guardar"
          >
            {iconeGuardar}
            {guardar.texto}
          </Button>
        </div>
      </div>
    </form>
  );
}

// Uma linha da lista: o número, a data, o tipo, o resumo e quem o escreveu.
function LinhaContacto({
  linha, acoesAtivas, guardarNo, ecra, aoPedirApagar,
}) {
  return (
    <li className="space-y-2 py-4 first:pt-0 last:pb-0" data-testid="crm-contacto">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h3 className="font-semibold" data-testid="crm-contacto-numero">{linha.titulo}</h3>
        <p className="text-sm font-semibold text-muted-foreground">{`${linha.data} · ${linha.tipo}`}</p>
      </div>
      <p className="whitespace-pre-wrap [overflow-wrap:anywhere]" data-testid="crm-contacto-texto">{linha.resumo}</p>
      <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]" data-testid="crm-contacto-autor">
        {linha.corrigido ? `${linha.autor} · ${TEXTO_CORRIGIDO}` : linha.autor}
      </p>
      {linha.podeAlterar && (
        <div className="flex flex-wrap gap-2">
          <Button
            ref={guardarNo(alvoCorrigir(linha.id))}
            type="button"
            variant="outline"
            className="h-11"
            disabled={!acoesAtivas}
            onClick={() => ecra?.abrirCorrecao(linha.id)}
            data-testid="crm-contacto-corrigir"
          >
            <Pencil aria-hidden="true" />
            {TEXTO_CORRIGIR}
            <span className="sr-only">{` o ${linha.titulo}`}</span>
          </Button>
          <Button
            ref={guardarNo(alvoApagar(linha.id))}
            type="button"
            variant="outline"
            className="h-11 border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive"
            disabled={!acoesAtivas}
            onClick={() => aoPedirApagar(linha.id)}
            data-testid="crm-contacto-apagar"
          >
            <Trash2 aria-hidden="true" />
            {TEXTO_APAGAR}
            <span className="sr-only">{` o ${linha.titulo}`}</span>
          </Button>
        </div>
      )}
    </li>
  );
}

export default function ContactosLoja({ lojaId }) {
  const idTitulo = useId();
  const nos = useRef({});
  const primeiraEscolhaApagar = useRef(null);
  // O botão "Apagar" que abriu a pergunta: é para ele que o foco volta quando ela fecha.
  const alvoDaPergunta = useRef(null);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarContactos({ lojaId }).vista);
  // O que deve receber o foco quando o ecrã já o mostrar.
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

  const guardarNo = (alvo) => (no) => {
    if (no) nos.current[alvo] = no;
    else delete nos.current[alvo];
  };

  // Depois do `destruir()` o ecrã já não chama nada (nem a vista, nem o aviso, nem o foco).
  useEffect(() => {
    const criado = criarContactos({
      api: API,
      rede: REDE,
      lojaId,
      novoUuid: novoUuid4,
      aoMudarVista: setVista,
      aoFocar: (alvo) => {
        focoPendente.current = alvo;
        setPedidosDeFoco((n) => n + 1);
      },
      aoAvisar: (texto) => toast.success(texto),
    });
    setEcra(criado);
    criado.iniciar();
    return () => criado.destruir();
  }, [lojaId]);

  // O foco pedido pelo ecrã, depois de o React mostrar o que vai recebê-lo.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    (nos.current[alvo] ?? nos.current[ALVO_ADICIONAR])?.focus();
  }, [pedidosDeFoco, vista]);

  const {
    estado, falha, linhas, bloco, apagar,
  } = vista;

  return (
    <section aria-labelledby={idTitulo} className="space-y-4 rounded-2xl border bg-card p-4 md:p-6" data-testid="crm-contactos">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={idTitulo} className="font-heading text-lg font-semibold">{TITULO_CONTACTOS}</h2>
        <Button
          ref={guardarNo(ALVO_ADICIONAR)}
          type="button"
          variant="outline"
          className="h-11 w-full sm:w-auto"
          disabled={!vista.adicionar.ativo}
          onClick={() => ecra?.abrirNovo()}
          data-testid="crm-contactos-adicionar"
        >
          <Plus aria-hidden="true" />
          {TEXTO_ADICIONAR_CONTACTO}
        </Button>
      </div>

      {vista.alerta && (
        <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-contactos-alerta">
          {vista.alerta}
        </p>
      )}

      {bloco && <BlocoContacto bloco={bloco} guardarNo={guardarNo} ecra={ecra} />}

      {estado === 'a_carregar' && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="crm-contactos-a-carregar">
          <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {TEXTO_A_CARREGAR_CONTACTOS}
        </p>
      )}

      {estado === 'falha' && (
        <div className="grid justify-items-start gap-3">
          <p role="alert" className="text-sm font-medium text-destructive [overflow-wrap:anywhere]" data-testid="crm-contactos-falha">
            {falha.mensagem}
          </p>
          <Button type="button" variant="outline" className="h-11" onClick={() => ecra?.tentarDeNovo()} disabled={falha.aTentar}>
            {TEXTO_TENTAR_DE_NOVO}
          </Button>
        </div>
      )}

      {vista.semContactos && (
        <p className="text-sm text-muted-foreground" data-testid="crm-contactos-vazio">{TEXTO_SEM_CONTACTOS}</p>
      )}

      {linhas.length > 0 && (
        <ul className="m-0 list-none divide-y p-0" data-testid="crm-contactos-lista">
          {linhas.map((linha) => (
            <LinhaContacto
              key={linha.id}
              linha={linha}
              acoesAtivas={vista.acoesAtivas}
              guardarNo={guardarNo}
              ecra={ecra}
              aoPedirApagar={(id) => {
                alvoDaPergunta.current = alvoApagar(id);
                ecra?.pedirApagar(id);
              }}
            />
          ))}
        </ul>
      )}

      <AlertDialog
        open={apagar !== null}
        onOpenChange={(abrir) => {
          if (!abrir) ecra?.responderApagar(null);
        }}
      >
        {apagar && (
          <AlertDialogContent
            className="w-[calc(100%-2rem)] max-w-[26rem] rounded-2xl"
            onOpenAutoFocus={(evento) => {
              // O foco vai para a primeira escolha: a que não apaga.
              evento.preventDefault();
              primeiraEscolhaApagar.current?.focus();
            }}
            onCloseAutoFocus={(evento) => {
              evento.preventDefault();
              nos.current[alvoDaPergunta.current]?.focus();
            }}
            data-testid="crm-contacto-dialogo-apagar"
          >
            <AlertDialogTitle className="text-base font-semibold">{apagar.pergunta}</AlertDialogTitle>
            <AlertDialogDescription className="text-base text-foreground">{apagar.descricao}</AlertDialogDescription>
            <div className="flex flex-col gap-2">
              {apagar.botoes.map((botao, i) => (
                <Button
                  key={botao.valor ?? 'cancelar'}
                  ref={i === 0 ? primeiraEscolhaApagar : undefined}
                  type="button"
                  variant={VARIANTES_APAGAR[botao.variante] ?? 'outline'}
                  className="h-auto min-h-11 w-full whitespace-normal py-2"
                  onClick={() => ecra?.responderApagar(botao.valor)}
                >
                  {botao.texto}
                </Button>
              ))}
            </div>
          </AlertDialogContent>
        )}
      </AlertDialog>
    </section>
  );
}
