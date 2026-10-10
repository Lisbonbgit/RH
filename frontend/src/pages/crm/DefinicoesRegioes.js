// Definições › Regiões (plano T2.30; desenho original §6.7): as regiões que
// filtram as lojas no mapa. Porta do componente
// public/assets/js/componentes/definicoes-regioes.js do CRM autónomo, no
// aspeto do portal.
//
// As regras estão em `lib/crm/regioes.js` (com testes): esta página cria o
// ecrã num `useEffect`, desenha a `vista` que ele entrega e passa-lhe o que a
// pessoa faz.
//  - A lista pela ordem das regiões, cada uma com Subir, Descer, Mudar o nome
//    e Apagar (o nome acessível de cada botão diz a região). Enquanto a ordem
//    grava, os Subir/Descer ficam com `aria-disabled` (e não `disabled`): o
//    foco fica no botão tocado. Ao mudar uma região de sítio, o React muda nós
//    de sítio e o browser tira-lhes o foco: o ecrã diz para onde ele vai, e o
//    que o tinha volta a tê-lo (como o `desenhar` do autónomo).
//  - Mudar o nome abre o campo na própria linha; Apagar pergunta num
//    `AlertDialog` (o foco na escolha que não apaga, e devolvido ao botão ao
//    fechar; apagada, o foco vai para o título). A mensagem de uma região que
//    não se apaga (tem lojas) fica nessa linha.
//  - "Nova região" e Adicionar por baixo da lista; os erros junto ao campo.
//  - Os avisos são toasts do sonner: de sucesso, e de erro sem sítio próprio
//    (a ordem que não gravou, uma região que outra pessoa apagou).
// Os nomes entram como texto (o React escapa-os).
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  ArrowDown, ArrowUp, Loader2, Pencil, Plus, Save, Trash2,
} from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import {
  alterarRegiao, apagarRegiao, criarRegiao, listarRegioes,
} from '../../lib/crm/api';
import {
  NOME_MAXIMO_REGIAO,
  TEXTO_A_ADICIONAR,
  TEXTO_A_CARREGAR_REGIOES,
  TEXTO_A_GUARDAR,
  TEXTO_CANCELAR,
  TEXTO_DESCER,
  TEXTO_DESCRICAO_REGIOES,
  TEXTO_MUDAR_NOME,
  TEXTO_NOVA_REGIAO,
  TEXTO_SEM_REGIOES,
  TEXTO_SUBIR,
  TITULO_REGIOES,
  criarRegioes,
} from '../../lib/crm/regioes';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  listarRegioes: () => listarRegioes(),
  criarRegiao: (corpo) => criarRegiao(corpo),
  alterarRegiao: (id, corpo) => alterarRegiao(id, corpo),
  apagarRegiao: (id) => apagarRegiao(id),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const VARIANTES_APAGAR = Object.freeze({ normal: 'outline', perigo: 'destructive' });

const CLASSE_INVALIDO = 'aria-[invalid=true]:border-destructive';
// aria-disabled (e não disabled) enquanto grava: o foco fica no botão em que se tocou.
const CLASSE_ACAO = 'h-11 aria-disabled:cursor-not-allowed aria-disabled:opacity-60';
const CLASSE_PERIGO = 'border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive';

// O elemento de uma região que deve receber o foco: `data-foco="<alvo>:<id>"`.
const marcaFoco = (alvo, id) => `${alvo}:${id}`;

export default function DefinicoesRegioes() {
  const idTitulo = useId();
  const idNova = useId();
  const idErroNova = `${idNova}-erro`;
  const seccao = useRef(null);
  const titulo = useRef(null);
  const lista = useRef(null);
  const campoNova = useRef(null);
  const primeiraEscolha = useRef(null);
  // O "Apagar" em que se tocou: o foco volta para lá quando a pergunta fecha.
  const botaoQueAbriu = useRef(null);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarRegioes({ rede: REDE }).vista);
  // O que deve receber o foco quando o ecrã já o mostrar.
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);
  // O elemento que tinha o foco antes de o React mexer na página (lido ao desenhar).
  const focadoAntes = useRef(null);
  focadoAntes.current = typeof document === 'undefined' ? null : document.activeElement;

  useEffect(() => {
    let ativo = true;
    const criado = criarRegioes({
      api: API,
      rede: REDE,
      aoMudarVista: (nova) => {
        if (ativo) setVista(nova);
      },
      // O mesmo aviso outra vez (ex.: "Ordem guardada" a cada Subir) troca o que está à vista, sem os empilhar.
      aoAvisar: (texto) => {
        if (ativo) toast.success(texto, { id: `crm-regioes-${texto}` });
      },
      aoAvisarErro: (texto) => {
        if (ativo) toast.error(texto);
      },
      aoFocar: (alvo) => {
        if (!ativo) return;
        focoPendente.current = alvo;
        setPedidosDeFoco((n) => n + 1);
      },
    });
    setEcra(criado);
    setVista(criado.vista);
    criado.iniciar();
    return () => {
      ativo = false;
      criado.destruir();
    };
  }, []);

  // Uma região que mudou de sítio: o browser tira o foco aos nós que o React muda de sítio. O que o tinha (e
  // ainda está na lista) volta a tê-lo, se o foco não foi para mais lado nenhum.
  useLayoutEffect(() => {
    const antes = focadoAntes.current;
    const agora = document.activeElement;
    if (!antes || antes === agora || !lista.current?.contains(antes)) return;
    if (agora && agora !== document.body) return;
    antes.focus();
  });

  // O foco pedido pelo ecrã, depois de o React mostrar o que vai recebê-lo.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    if (alvo === 'titulo') titulo.current?.focus();
    else if (alvo === 'nova') campoNova.current?.focus();
    else seccao.current?.querySelector(`[data-foco="${marcaFoco(alvo.alvo, alvo.id)}"]`)?.focus();
  }, [pedidosDeFoco, vista]);

  const {
    estado, falha, vazio, linhas, nova, pergunta,
  } = vista;

  return (
    <section ref={seccao} aria-labelledby={idTitulo} className="space-y-4" data-testid="crm-regioes">
      <div className="space-y-1">
        <h2 id={idTitulo} ref={titulo} tabIndex={-1} className="font-heading text-lg font-semibold focus:outline-none">
          {TITULO_REGIOES}
        </h2>
        <p className="text-sm text-muted-foreground">{TEXTO_DESCRICAO_REGIOES}</p>
      </div>

      {estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR_REGIOES} />}

      {estado === 'falha' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
          <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-regioes-falha">
            {falha.mensagem}
          </p>
          <Button type="button" className="h-11" onClick={() => ecra?.tentarDeNovo()} disabled={falha.aTentar}>
            Tentar novamente
          </Button>
        </div>
      )}

      {estado === 'pronto' && (
        <>
          {/* A lista não voltou a carregar (ex.: depois de a ordem falhar): a que está à vista fica. */}
          {falha && (
            <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-destructive/40 bg-destructive/5 p-3">
              <p role="alert" className="min-w-0 flex-1 text-sm font-medium text-destructive" data-testid="crm-regioes-falha">
                {falha.mensagem}
              </p>
              <Button type="button" variant="outline" className="h-11" onClick={() => ecra?.tentarDeNovo()} disabled={falha.aTentar}>
                Tentar novamente
              </Button>
            </div>
          )}

          <div className="rounded-2xl border bg-card p-3 md:p-4">
            {vazio ? (
              <p className="p-2 text-sm text-muted-foreground" data-testid="crm-regioes-vazio">{TEXTO_SEM_REGIOES}</p>
            ) : (
              <ol ref={lista} aria-labelledby={idTitulo} className="divide-y" data-testid="crm-regioes-lista">
                {linhas.map((linha) => (
                  <li key={linha.id} className="py-3 first:pt-1 last:pb-1" data-testid="crm-regiao">
                    {linha.edicao ? (
                      // noValidate: as mensagens são as do servidor (pt-PT), não as do browser.
                      <form
                        noValidate
                        className="space-y-2"
                        onSubmit={(evento) => {
                          evento.preventDefault();
                          ecra?.guardarNome();
                        }}
                        data-testid="crm-regiao-edicao"
                      >
                        <Label htmlFor={`${idNova}-${linha.id}`} className="[overflow-wrap:anywhere]">
                          {linha.rotulos.novoNome}
                        </Label>
                        <Input
                          id={`${idNova}-${linha.id}`}
                          value={linha.edicao.valor}
                          onChange={(evento) => ecra?.mudarNome(evento.target.value)}
                          maxLength={NOME_MAXIMO_REGIAO}
                          autoComplete="off"
                          disabled={linha.edicao.aGuardar}
                          className={`h-11 ${CLASSE_INVALIDO}`}
                          aria-invalid={linha.edicao.erro ? 'true' : undefined}
                          aria-describedby={linha.edicao.erro ? `${idNova}-${linha.id}-erro` : undefined}
                          data-foco={marcaFoco('nome', linha.id)}
                        />
                        {linha.edicao.erro && (
                          <p id={`${idNova}-${linha.id}-erro`} className="text-sm font-medium text-destructive">
                            {linha.edicao.erro}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-2">
                          <Button type="submit" className="h-11 flex-1 sm:flex-none" disabled={!linha.edicao.botao.ativo}>
                            {linha.edicao.botao.texto === TEXTO_A_GUARDAR
                              ? <Loader2 className="animate-spin" aria-hidden="true" />
                              : <Save aria-hidden="true" />}
                            {linha.edicao.botao.texto}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-11 flex-1 sm:flex-none"
                            disabled={linha.edicao.aGuardar}
                            onClick={() => ecra?.cancelarEdicao()}
                          >
                            {TEXTO_CANCELAR}
                          </Button>
                        </div>
                      </form>
                    ) : (
                      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <span className="min-w-0 font-medium [overflow-wrap:anywhere]" data-testid="crm-regiao-nome">
                          {linha.nome}
                        </span>
                        <div className="grid shrink-0 grid-cols-2 gap-2 sm:flex sm:flex-wrap md:justify-end">
                          <Button
                            type="button"
                            variant="outline"
                            className={CLASSE_ACAO}
                            aria-label={linha.rotulos.subir}
                            disabled={!linha.podeSubir}
                            aria-disabled={linha.ocupada || undefined}
                            onClick={() => ecra?.subir(linha.id)}
                            data-foco={marcaFoco('subir', linha.id)}
                          >
                            <ArrowUp aria-hidden="true" />
                            {TEXTO_SUBIR}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className={CLASSE_ACAO}
                            aria-label={linha.rotulos.descer}
                            disabled={!linha.podeDescer}
                            aria-disabled={linha.ocupada || undefined}
                            onClick={() => ecra?.descer(linha.id)}
                            data-foco={marcaFoco('descer', linha.id)}
                          >
                            <ArrowDown aria-hidden="true" />
                            {TEXTO_DESCER}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-11"
                            aria-label={linha.rotulos.mudar}
                            onClick={() => ecra?.abrirEdicao(linha.id)}
                            data-foco={marcaFoco('mudar', linha.id)}
                          >
                            <Pencil aria-hidden="true" />
                            {TEXTO_MUDAR_NOME}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className={`${CLASSE_ACAO} ${CLASSE_PERIGO}`}
                            aria-label={linha.rotulos.apagar}
                            aria-disabled={!linha.apagar.ativo || undefined}
                            onClick={(evento) => {
                              if (!linha.apagar.ativo) return;
                              botaoQueAbriu.current = evento.currentTarget;
                              ecra?.pedirApagar(linha.id);
                            }}
                            data-testid="crm-regiao-apagar"
                          >
                            {linha.apagar.ativo
                              ? <Trash2 aria-hidden="true" />
                              : <Loader2 className="animate-spin" aria-hidden="true" />}
                            {linha.apagar.texto}
                          </Button>
                        </div>
                      </div>
                    )}
                    {linha.erro && (
                      <p role="alert" className="mt-2 text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-regiao-erro">
                        {linha.erro}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>

          {/* noValidate: as mensagens são as do servidor (pt-PT), não as do browser. */}
          <form
            noValidate
            className="space-y-2 rounded-2xl border bg-card p-4 md:p-6"
            onSubmit={(evento) => {
              evento.preventDefault();
              ecra?.adicionar();
            }}
            data-testid="crm-regioes-adicionar"
          >
            <Label htmlFor={idNova}>{TEXTO_NOVA_REGIAO}</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id={idNova}
                ref={campoNova}
                value={nova.valor}
                onChange={(evento) => ecra?.mudarNova(evento.target.value)}
                maxLength={NOME_MAXIMO_REGIAO}
                autoComplete="off"
                className={`h-11 ${CLASSE_INVALIDO}`}
                aria-invalid={nova.erro ? 'true' : undefined}
                aria-describedby={nova.erro ? idErroNova : undefined}
                data-testid="crm-regioes-nova"
              />
              <Button type="submit" className="h-11 shrink-0" disabled={!nova.botao.ativo} data-testid="crm-regioes-botao-adicionar">
                {nova.botao.texto === TEXTO_A_ADICIONAR
                  ? <Loader2 className="animate-spin" aria-hidden="true" />
                  : <Plus aria-hidden="true" />}
                {nova.botao.texto}
              </Button>
            </div>
            {nova.erro && <p id={idErroNova} className="text-sm font-medium text-destructive">{nova.erro}</p>}
          </form>
        </>
      )}

      <AlertDialog
        open={pergunta !== null}
        onOpenChange={(abrir) => {
          if (!abrir) ecra?.responderApagar(null);
        }}
      >
        {pergunta && (
          <AlertDialogContent
            className="w-[calc(100%-2rem)] max-w-[26rem] rounded-2xl"
            onOpenAutoFocus={(evento) => {
              // O foco vai para a primeira escolha: a que não apaga.
              evento.preventDefault();
              primeiraEscolha.current?.focus();
            }}
            onCloseAutoFocus={(evento) => {
              evento.preventDefault();
              botaoQueAbriu.current?.focus();
            }}
            data-testid="crm-dialogo-apagar-regiao"
          >
            <AlertDialogTitle className="text-base font-semibold [overflow-wrap:anywhere]">{pergunta.pergunta}</AlertDialogTitle>
            <AlertDialogDescription className="text-base text-foreground">{pergunta.aviso}</AlertDialogDescription>
            <div className="flex flex-col gap-2">
              {pergunta.botoes.map((botao, i) => (
                <Button
                  key={botao.valor ?? 'cancelar'}
                  ref={i === 0 ? primeiraEscolha : undefined}
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
