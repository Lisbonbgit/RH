// Definições › Membros (plano T2.29; desenho §3.1): quem entra no CRM e com
// que perfil. Porta do componente
// public/assets/js/componentes/definicoes-utilizadores.js do CRM autónomo, no
// aspeto do portal.
//
// As regras estão em `lib/crm/membros.js` (com testes): esta página cria o
// ecrã num `useEffect`, desenha a `vista` que ele entrega e passa-lhe o que a
// pessoa faz.
//  - A tabela (nome, email, tipo de conta, perfil, ações). No telemóvel cada
//    linha é um cartão, com o rótulo de cada célula tirado do `data-rotulo`;
//    os `role` explícitos mantêm a tabela para os leitores de ecrã (o Safari
//    tira-a quando o CSS muda o `display` das células), como no autónomo.
//  - O admin principal e a própria conta ficam sem ações (a nota da linha
//    diz porquê). O perfil muda num `Select` e grava logo; "Retirar" pergunta
//    num `AlertDialog` (o foco na escolha que não retira, e devolvido ao botão
//    ao fechar; retirado, o foco vai para o título).
//  - "Adicionar membro": a conta do portal e o perfil (Utilizador por
//    omissão); os erros do 422 junto aos campos.
//  - Os avisos são toasts do sonner: de sucesso, e de erro com a mensagem do
//    servidor (409, 404, sem rede).
// Os nomes e os emails entram como texto (o React escapa-os).
import React, { forwardRef, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import * as SelectPrimitive from '@radix-ui/react-select';
import { toast } from 'sonner';
import { Check, Loader2, Trash2, UserPlus } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Label } from '../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '../../components/ui/table';
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import { useAuth } from '../../contexts/AuthContext';
import {
  adicionarMembro, listarCandidatos, listarMembros, mudarPerfilMembro, retirarMembro,
} from '../../lib/crm/api';
import {
  COLUNAS_MEMBROS,
  TEXTO_A_ADICIONAR,
  TEXTO_A_CARREGAR_MEMBROS,
  TEXTO_ADICIONAR_TITULO,
  TEXTO_ADMIN_PRINCIPAL,
  TEXTO_CONTA,
  TEXTO_DESCRICAO_MEMBROS,
  TEXTO_ESCOLHER_CONTA,
  TEXTO_PERFIL,
  TEXTO_PERFIL_DESCONHECIDO,
  TEXTO_RETIRAR,
  TEXTO_SEM_CANDIDATOS,
  TITULO_MEMBROS,
  criarMembros,
} from '../../lib/crm/membros';
import { PERFIS } from '../../lib/crm/perfis';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  listarMembros: () => listarMembros(),
  listarCandidatos: () => listarCandidatos(),
  adicionarMembro: (corpo) => adicionarMembro(corpo),
  mudarPerfilMembro: (id, perfil) => mudarPerfilMembro(id, perfil),
  retirarMembro: (id) => retirarMembro(id),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const VARIANTES_RETIRAR = Object.freeze({ normal: 'outline', perigo: 'destructive' });

// No telemóvel, cada célula mostra o rótulo da coluna (`data-rotulo`) à esquerda; a partir do `md`, tabela.
const CLASSE_CELULA = [
  'flex min-w-0 items-center justify-between gap-3 px-0 py-1.5',
  'before:shrink-0 before:text-sm before:font-medium before:text-muted-foreground before:content-[attr(data-rotulo)]',
  'md:table-cell md:px-2 md:py-2 md:before:content-none',
].join(' ');

const CLASSE_INVALIDO = 'aria-[invalid=true]:border-destructive';

// Uma conta no "Adicionar": o nome e, por baixo, o email e o tipo de conta. Só o nome fica no `ItemText` (é o
// que o campo fechado mostra e o que a escrita rápida procura); o `SelectItem` do shadcn punha tudo lá dentro.
const OpcaoConta = forwardRef(({ nome, detalhe, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className="relative flex min-h-11 w-full cursor-default select-none flex-col items-start justify-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
    {...props}
  >
    <span className="absolute right-2 top-1/2 flex h-3.5 w-3.5 -translate-y-1/2 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-4 w-4" aria-hidden="true" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{nome}</SelectPrimitive.ItemText>
    {detalhe && <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{detalhe}</span>}
  </SelectPrimitive.Item>
));
OpcaoConta.displayName = 'OpcaoConta';

// Um email parte-se de preferência antes do "@" (e só no fim de tudo noutro sítio).
function Email({ texto }) {
  const arroba = texto.indexOf('@');
  if (arroba <= 0) return texto;
  return (
    <>
      {texto.slice(0, arroba)}
      <wbr />
      {texto.slice(arroba)}
    </>
  );
}

export default function DefinicoesMembros() {
  const { user } = useAuth();
  const euId = typeof user?.id === 'string' ? user.id : null;
  const idTitulo = useId();
  const idNovo = useId();
  const idConta = useId();
  const idPerfil = useId();
  const titulo = useRef(null);
  const campoConta = useRef(null);
  const campoPerfil = useRef(null);
  const primeiraEscolha = useRef(null);
  // O "Retirar" em que se tocou: o foco volta para lá quando a pergunta fecha.
  const botaoQueAbriu = useRef(null);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarMembros({ rede: REDE, euId }).vista);
  // O que deve receber o foco quando o ecrã já o mostrar (o título, ou o campo com erro de um 422).
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

  useEffect(() => {
    let ativo = true;
    const criado = criarMembros({
      api: API,
      rede: REDE,
      euId,
      aoMudarVista: (nova) => {
        if (ativo) setVista(nova);
      },
      aoAvisar: (texto) => {
        if (ativo) toast.success(texto);
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
  }, [euId]);

  // O foco pedido pelo ecrã, depois de o React mostrar o que vai recebê-lo.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    if (alvo === 'titulo') titulo.current?.focus();
    else if (alvo === 'user_id') campoConta.current?.focus();
    else if (alvo === 'perfil') campoPerfil.current?.focus();
  }, [pedidosDeFoco, vista]);

  const { estado, linhas, novo, pergunta } = vista;
  const erroDe = (campo) => novo.erros[campo] ?? null;
  const idErro = (campo) => `${idNovo}-erro-${campo}`;
  const descricaoPerfil = `${idNovo}-descricao-perfil`;
  const comErro = (campo, extra = null) => {
    const ids = [erroDe(campo) ? idErro(campo) : null, extra].filter(Boolean).join(' ');
    return {
      'aria-invalid': erroDe(campo) ? 'true' : undefined,
      'aria-describedby': ids || undefined,
    };
  };

  return (
    <section aria-labelledby={idTitulo} className="space-y-4" data-testid="crm-membros">
      <div className="space-y-1">
        <h2 id={idTitulo} ref={titulo} tabIndex={-1} className="font-heading text-lg font-semibold focus:outline-none">
          {TITULO_MEMBROS}
        </h2>
        <p className="text-sm text-muted-foreground">{TEXTO_DESCRICAO_MEMBROS}</p>
      </div>

      {estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR_MEMBROS} />}

      {estado === 'falha' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
          <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-membros-falha">
            {vista.falha.mensagem}
          </p>
          <Button type="button" className="h-11" onClick={() => ecra?.tentarDeNovo()} disabled={vista.falha.aTentar}>
            Tentar novamente
          </Button>
        </div>
      )}

      {estado === 'pronto' && (
        <>
          <div className="rounded-2xl border bg-card p-3 md:p-4">
            <Table role="table" aria-labelledby={idTitulo} className="block md:table" data-testid="crm-membros-tabela">
              <TableHeader role="rowgroup" className="sr-only md:not-sr-only md:table-header-group">
                <TableRow role="row">
                  {COLUNAS_MEMBROS.map((coluna) => (
                    <TableHead key={coluna} role="columnheader" scope="col">{coluna}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody
                role="rowgroup"
                // O TableBody tira a borda à última linha; no telemóvel cada linha é um cartão, com borda.
                className="block space-y-3 md:table-row-group md:space-y-0 [&_tr:last-child]:border md:[&_tr:last-child]:border-0"
              >
                {linhas.map((linha) => (
                  <TableRow
                    key={linha.chave}
                    role="row"
                    aria-busy={linha.ocupada || undefined}
                    className="block rounded-xl border p-3 hover:bg-transparent md:table-row md:rounded-none md:border-0 md:border-b md:p-0 md:hover:bg-muted/50"
                    data-testid="crm-membro"
                  >
                    <TableCell role="cell" data-rotulo={COLUNAS_MEMBROS[0]} className={CLASSE_CELULA}>
                      <span className="flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1 text-right md:justify-start md:text-left">
                        <span
                          className={`font-medium [overflow-wrap:anywhere] ${linha.contaApagada ? 'italic text-muted-foreground' : ''}`}
                          data-testid="crm-membro-nome"
                        >
                          {linha.nome}
                        </span>
                        {linha.adminPrincipal && (
                          <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                            {TEXTO_ADMIN_PRINCIPAL}
                          </span>
                        )}
                      </span>
                    </TableCell>
                    <TableCell role="cell" data-rotulo={COLUNAS_MEMBROS[1]} className={CLASSE_CELULA}>
                      <span className="min-w-0 break-words text-right md:text-left"><Email texto={linha.email} /></span>
                    </TableCell>
                    <TableCell role="cell" data-rotulo={COLUNAS_MEMBROS[2]} className={CLASSE_CELULA}>
                      <span className="text-right md:text-left">{linha.tipoConta}</span>
                    </TableCell>
                    <TableCell role="cell" data-rotulo={COLUNAS_MEMBROS[3]} className={CLASSE_CELULA}>
                      {linha.acoes ? (
                        <Select value={linha.perfil ?? ''} onValueChange={(valor) => ecra?.mudarPerfil(linha.id, valor)}>
                          <SelectTrigger
                            aria-label={linha.rotuloPerfilAcessivel}
                            className="h-11 w-44 max-w-full"
                            data-testid="crm-membro-perfil"
                          >
                            <SelectValue placeholder={TEXTO_PERFIL_DESCONHECIDO} />
                          </SelectTrigger>
                          <SelectContent>
                            {PERFIS.map((perfil) => (
                              <SelectItem key={perfil.valor} value={perfil.valor} className="min-h-11">
                                {perfil.rotulo}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <span className="text-right md:text-left">{linha.rotuloPerfil}</span>
                      )}
                    </TableCell>
                    <TableCell role="cell" data-rotulo={COLUNAS_MEMBROS[4]} className={CLASSE_CELULA}>
                      {linha.acoes ? (
                        <Button
                          type="button"
                          variant="outline"
                          aria-label={linha.rotuloRetirarAcessivel}
                          // aria-disabled (e não disabled) enquanto grava: o foco fica no botão em que se tocou.
                          aria-disabled={linha.ocupada || undefined}
                          className="h-11 border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive aria-disabled:cursor-not-allowed aria-disabled:opacity-60"
                          onClick={(evento) => {
                            if (linha.ocupada) return;
                            botaoQueAbriu.current = evento.currentTarget;
                            ecra?.pedirRetirar(linha.id);
                          }}
                          data-testid="crm-membro-retirar"
                        >
                          {linha.ocupada ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
                          {TEXTO_RETIRAR}
                        </Button>
                      ) : (
                        <span className="text-right text-sm text-muted-foreground md:text-left" data-testid="crm-membro-nota">
                          {linha.nota}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* noValidate: as mensagens dos campos são as do servidor (pt-PT), não as do browser. */}
          <form
            noValidate
            aria-labelledby={idNovo}
            className="space-y-4 rounded-2xl border bg-card p-4 md:p-6"
            onSubmit={(evento) => {
              evento.preventDefault();
              ecra?.adicionar();
            }}
            data-testid="crm-membros-adicionar"
          >
            <h3 id={idNovo} className="font-heading text-base font-semibold">{TEXTO_ADICIONAR_TITULO}</h3>
            {novo.semCandidatos ? (
              <p className="text-sm text-muted-foreground" data-testid="crm-membros-sem-candidatos">{TEXTO_SEM_CANDIDATOS}</p>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor={idConta}>{TEXTO_CONTA}</Label>
                  <Select value={novo.userId} onValueChange={(valor) => ecra?.escolherConta(valor)}>
                    <SelectTrigger
                      id={idConta}
                      ref={campoConta}
                      className={`h-11 ${CLASSE_INVALIDO}`}
                      data-testid="crm-membros-conta"
                      {...comErro('user_id')}
                    >
                      <SelectValue placeholder={TEXTO_ESCOLHER_CONTA} />
                    </SelectTrigger>
                    <SelectContent>
                      {novo.opcoesConta.map((opcao) => (
                        <OpcaoConta key={opcao.valor} value={opcao.valor} nome={opcao.nome} detalhe={opcao.detalhe} />
                      ))}
                    </SelectContent>
                  </Select>
                  {erroDe('user_id') && (
                    <p id={idErro('user_id')} className="text-sm font-medium text-destructive">{erroDe('user_id')}</p>
                  )}
                </div>
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor={idPerfil}>{TEXTO_PERFIL}</Label>
                  <Select value={novo.perfil} onValueChange={(valor) => ecra?.escolherPerfil(valor)}>
                    <SelectTrigger
                      id={idPerfil}
                      ref={campoPerfil}
                      className={`h-11 ${CLASSE_INVALIDO}`}
                      data-testid="crm-membros-perfil"
                      {...comErro('perfil', descricaoPerfil)}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PERFIS.map((perfil) => (
                        <SelectItem key={perfil.valor} value={perfil.valor} className="min-h-11">{perfil.rotulo}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {erroDe('perfil') && (
                    <p id={idErro('perfil')} className="text-sm font-medium text-destructive">{erroDe('perfil')}</p>
                  )}
                  <p id={descricaoPerfil} className="text-sm text-muted-foreground" data-testid="crm-membros-descricao-perfil">
                    {novo.descricaoPerfil}
                  </p>
                </div>
              </div>
            )}
            <Button type="submit" className="h-11 w-full sm:w-auto" disabled={!novo.botao.ativo} data-testid="crm-membros-botao-adicionar">
              {novo.botao.texto === TEXTO_A_ADICIONAR
                ? <Loader2 className="animate-spin" aria-hidden="true" />
                : <UserPlus aria-hidden="true" />}
              {novo.botao.texto}
            </Button>
          </form>
        </>
      )}

      <AlertDialog
        open={pergunta !== null}
        onOpenChange={(abrir) => {
          if (!abrir) ecra?.responderRetirar(null);
        }}
      >
        {pergunta && (
          <AlertDialogContent
            className="w-[calc(100%-2rem)] max-w-[26rem] rounded-2xl"
            onOpenAutoFocus={(evento) => {
              // O foco vai para a primeira escolha: a que não retira.
              evento.preventDefault();
              primeiraEscolha.current?.focus();
            }}
            onCloseAutoFocus={(evento) => {
              evento.preventDefault();
              botaoQueAbriu.current?.focus();
            }}
            data-testid="crm-dialogo-retirar"
          >
            <AlertDialogTitle className="text-base font-semibold [overflow-wrap:anywhere]">{pergunta.pergunta}</AlertDialogTitle>
            <AlertDialogDescription className="text-base text-foreground">{pergunta.aviso}</AlertDialogDescription>
            <div className="flex flex-col gap-2">
              {pergunta.botoes.map((botao, i) => (
                <Button
                  key={botao.valor ?? 'cancelar'}
                  ref={i === 0 ? primeiraEscolha : undefined}
                  type="button"
                  variant={VARIANTES_RETIRAR[botao.variante] ?? 'outline'}
                  className="h-auto min-h-11 w-full whitespace-normal py-2"
                  onClick={() => ecra?.responderRetirar(botao.valor)}
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
