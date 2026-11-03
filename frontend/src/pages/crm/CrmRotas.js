// A página "Rotas", em `rotas` (plano F3 T3.37; desenho original §7.1: "Escolher o dia … Se já existir
// rota, abre-a"). Não é ecrã cheio (`ecraCheioDoCrm` só no planeador de um dia): fica com as margens do
// layout.
//
// As regras estão em `lib/crm/listaRotas.js` (com testes): esta página cria o ecrã num `useEffect`,
// desenha a `vista` que ele entrega e passa-lhe o que a pessoa faz.
//  - O campo da data e "Abrir" levam ao planeador de qualquer dia que exista (o passado abre só de
//    leitura; depois de hoje + 365, a mensagem do servidor por baixo do campo). Enter no campo também
//    abre. O porquê de "Abrir" estar desativado fica por baixo dele.
//  - "Hoje" é uma ligação para a rota de hoje, com o hoje do servidor (até a lista chegar, desativado).
//  - "Próximas" e "Anteriores" vêm do `listarRotas()` (hoje − 14 a hoje + 60): cada linha é uma ligação
//    para o planeador desse dia, "seg 12/10 · Planeada · 9 paragens".
//  - A falha mostra a mensagem e "Tentar novamente".
// Com outra casa (`/crm` ou `/admin/crm`, a `base`), o ecrã cria-se de novo. Os dados entram como texto (o
// React escapa-os).
import React, { Fragment, useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowRight, CalendarDays, ChevronRight, Route as IconeRota, // nunca `Route`: confundia-se com o `Route` do React Router
} from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import { baseCrm } from '../../lib/crm/acesso';
import { TEXTO_A_CARREGAR_DIAS, TEXTO_DIA } from '../../lib/crm/adicionarARota';
import { listarRotas } from '../../lib/crm/api';
import { criarListaRotas } from '../../lib/crm/listaRotas';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  listarRotas: () => listarRotas(),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const CLASSE_BOTAO = 'h-11 flex-1 sm:flex-none';

// Uma das duas listas ("Próximas" ou "Anteriores"): as ligações de cada dia, ou o texto da lista vazia.
function GrupoDeRotas({ grupo, testid }) {
  const idTitulo = useId();
  return (
    <section aria-labelledby={idTitulo} className="space-y-3" data-testid={testid}>
      <h2 id={idTitulo} className="font-heading text-lg font-semibold">{grupo.titulo}</h2>
      {grupo.vazia !== null ? (
        <p className="rounded-2xl border border-dashed p-4 text-sm text-muted-foreground" data-testid={`${testid}-vazia`}>
          {grupo.vazia}
        </p>
      ) : (
        <ul className="divide-y overflow-hidden rounded-2xl border bg-card">
          {grupo.linhas.map((linha) => (
            <li key={linha.data}>
              <Link
                to={linha.caminho}
                aria-current={linha.eHoje ? 'date' : undefined}
                className={`flex min-h-12 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${linha.eHoje ? 'bg-primary/5' : ''}`}
                data-testid="crm-rotas-linha"
              >
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                  <span className="font-semibold">{linha.dia}</span>
                  <span className="text-muted-foreground">
                    {[linha.estado, linha.paragens].filter((parte) => parte !== null).map((parte) => (
                      <Fragment key={parte}>
                        {' · '}
                        {parte}
                      </Fragment>
                    ))}
                  </span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function CrmRotas() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const base = baseCrm(pathname);
  const idDia = useId();
  const idFalta = `${idDia}-falta`;
  // O `navigate` do React Router muda com o caminho: o ecrã lê sempre o mais recente.
  const navegar = useRef(navigate);
  useEffect(() => {
    navegar.current = navigate;
  }, [navigate]);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarListaRotas({ base }).vista);

  // O `destruir()` ao sair faz que as respostas atrasadas e a rede já não mudem nada.
  useEffect(() => {
    const criado = criarListaRotas({
      api: API,
      rede: REDE,
      base,
      navegar: (caminho) => navegar.current(caminho),
      aoMudarVista: setVista,
    });
    setEcra(criado);
    setVista(criado.vista);
    criado.iniciar();
    return () => criado.destruir();
  }, [base]);

  const {
    estado, falha, abrir, hoje, proximas, anteriores, nota,
  } = vista;

  return (
    <div className="mx-auto max-w-3xl space-y-6 animate-fade-in" data-testid="crm-rotas">
      <PageHeader icon={IconeRota} title={vista.titulo} subtitle="CRM Purple House" />

      {/* noValidate: a mensagem é a da página (pt-PT), não a do browser. */}
      <form
        noValidate
        className="space-y-2 rounded-2xl border bg-card p-4 md:p-6"
        onSubmit={(evento) => {
          evento.preventDefault();
          ecra?.abrir();
        }}
        data-testid="crm-rotas-escolher"
      >
        <Label htmlFor={idDia}>{TEXTO_DIA}</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id={idDia}
            type="date"
            value={vista.data}
            max={vista.max ?? undefined}
            onChange={(evento) => ecra?.mudarDia(evento.target.value)}
            className="h-11 sm:max-w-xs"
            aria-describedby={idFalta}
            data-testid="crm-rotas-dia"
          />
          <div className="flex gap-2">
            <Button type="submit" className={CLASSE_BOTAO} disabled={!abrir.ativo} data-testid="crm-rotas-abrir">
              <ArrowRight aria-hidden="true" />
              {abrir.texto}
            </Button>
            {hoje.ativo ? (
              <Button asChild variant="outline" className={CLASSE_BOTAO}>
                <Link to={hoje.caminho} data-testid="crm-rotas-hoje">
                  <CalendarDays aria-hidden="true" />
                  {hoje.texto}
                </Link>
              </Button>
            ) : (
              <Button type="button" variant="outline" className={CLASSE_BOTAO} disabled data-testid="crm-rotas-hoje">
                <CalendarDays aria-hidden="true" />
                {hoje.texto}
              </Button>
            )}
          </div>
        </div>
        {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
        <p id={idFalta} aria-live="polite" className="text-sm text-muted-foreground" data-testid="crm-rotas-falta">
          {abrir.falta ?? ''}
        </p>
      </form>

      {estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR_DIAS} />}

      {estado === 'falha' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
          <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-rotas-falha">
            {falha.mensagem}
          </p>
          <Button
            type="button"
            className="h-11"
            onClick={() => ecra?.tentarDeNovo()}
            disabled={falha.aTentar}
            data-testid="crm-rotas-tentar"
          >
            Tentar novamente
          </Button>
        </div>
      )}

      {estado === 'pronto' && (
        <>
          <GrupoDeRotas grupo={proximas} testid="crm-rotas-proximas" />
          <GrupoDeRotas grupo={anteriores} testid="crm-rotas-anteriores" />
          {nota !== null && <p className="text-sm text-muted-foreground" data-testid="crm-rotas-nota">{nota}</p>}
        </>
      )}
    </div>
  );
}
