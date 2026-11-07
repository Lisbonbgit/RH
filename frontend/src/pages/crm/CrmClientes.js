// A página "Clientes", em `clientes` (desenho de 2026-11-07, §1): todas as lojas, de todas as fases, separadas
// pela fase e com pesquisa. Não é ecrã cheio e não usa o mapa: funciona sem o Google.
//
// As regras estão em `lib/crm/listaClientes.js` (com testes): esta página cria o ecrã num `useEffect`, desenha a
// `vista` que ele entrega e passa-lhe o que a pessoa faz.
//  - A pesquisa filtra enquanto se escreve; as pastilhas escolhem uma fase de cada vez.
//  - Cada linha é um `Link` para a ficha, com `state: {origem: 'clientes'}`: a ficha mostra "Voltar à lista".
//  - A pesquisa e a fase ficam no `sessionStorage` (`crm.clientes`), para continuarem lá ao voltar da ficha.
//  - "Limpar pesquisa" só limpa o texto, e o foco volta ao campo.
// Importa o `crm.css` porque as páginas são lazy: sem ele, a cor das pastilhas e das linhas não aparecia a quem
// abre a lista diretamente. Com outra casa (`/crm` ou `/admin/crm`, a `base`), o ecrã cria-se de novo. Os dados
// entram como texto (o React escapa-os).
import React, { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronRight, MapPinPlus, Users } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import { baseCrm } from '../../lib/crm/acesso';
import { listarLojas } from '../../lib/crm/api';
import { CLASSE_PASTILHA, ROTULO_FASE } from '../../lib/crm/formularioLoja';
import {
  TEXTO_A_CARREGAR, TEXTO_LIMPAR_PESQUISA, TEXTO_NOVA_LOJA, TEXTO_PESQUISA, TEXTO_SEM_LOJAS, criarListaClientes,
} from '../../lib/crm/listaClientes';
import { criarEstadoRede } from '../../lib/crm/rede';
import '../../components/crm/crm.css';

const API = Object.freeze({
  listarLojas: () => listarLojas(),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

// O sessionStorage pode não existir ou lançar (browser bloqueado, modo privado): a lista funciona na mesma, só não
// se lembra da pesquisa (o listaClientes.js também apanha os erros de leitura e escrita).
function armazenamento() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

// Uma linha da lista: a cor, o nome, a fase em texto e os detalhes.
function LinhaCliente({ linha }) {
  return (
    <li>
      <Link
        to={linha.caminho}
        state={linha.estado}
        className="flex min-h-12 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        data-testid="crm-clientes-linha"
      >
        {linha.classeCor && <span aria-hidden="true" className={linha.classeCor} />}
        <span className="min-w-0 flex-1 space-y-0.5 [overflow-wrap:anywhere]">
          <span className="block font-semibold">{linha.nome}</span>
          <span className="block text-sm font-semibold text-muted-foreground">{linha.fase}</span>
          <span className="flex flex-wrap gap-x-3 text-sm text-muted-foreground">
            {linha.detalhes.map((detalhe, i) => (
              <span key={i} className="min-w-0">
                {detalhe.rotulo && <strong className="font-semibold text-foreground">{`${detalhe.rotulo} `}</strong>}
                {detalhe.texto}
              </span>
            ))}
          </span>
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>
    </li>
  );
}

export default function CrmClientes() {
  const { pathname } = useLocation();
  const base = baseCrm(pathname);
  const idPesquisa = useId();
  const idFases = useId();
  const campoPesquisa = useRef(null);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarListaClientes({ base, storage: armazenamento() }).vista);

  // O `destruir()` ao sair faz que as respostas atrasadas e a rede já não mudem nada.
  useEffect(() => {
    const criado = criarListaClientes({
      api: API,
      rede: REDE,
      base,
      storage: armazenamento(),
      aoMudarVista: setVista,
    });
    setEcra(criado);
    setVista(criado.vista);
    criado.iniciar();
    return () => criado.destruir();
  }, [base]);

  const {
    estado, falha, pastilhas, linhas, semResultados,
  } = vista;

  return (
    <div className="mx-auto max-w-3xl space-y-6 animate-fade-in" data-testid="crm-clientes">
      <PageHeader icon={Users} title={vista.titulo} subtitle="CRM Purple House" />

      {estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR} />}

      {estado === 'falha' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
          <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-clientes-falha">
            {falha.mensagem}
          </p>
          <Button
            type="button"
            className="h-11"
            onClick={() => ecra?.tentarDeNovo()}
            disabled={falha.aTentar}
            data-testid="crm-clientes-tentar"
          >
            Tentar novamente
          </Button>
        </div>
      )}

      {estado === 'sem_lojas' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center" data-testid="crm-clientes-sem-lojas">
          <p className="max-w-md font-medium">{TEXTO_SEM_LOJAS}</p>
          <Button asChild className="h-11">
            <Link to={vista.novaLoja}>
              <MapPinPlus aria-hidden="true" />
              {TEXTO_NOVA_LOJA}
            </Link>
          </Button>
        </div>
      )}

      {estado === 'pronto' && (
        <>
          <div className="space-y-4 rounded-2xl border bg-card p-4 md:p-6">
            <div className="space-y-1.5">
              <Label htmlFor={idPesquisa}>{TEXTO_PESQUISA}</Label>
              <Input
                ref={campoPesquisa}
                id={idPesquisa}
                type="search"
                value={vista.pesquisa}
                onChange={(evento) => ecra?.mudarPesquisa(evento.target.value)}
                autoComplete="off"
                className="h-11"
                data-testid="crm-clientes-pesquisa"
              />
            </div>
            <fieldset className="m-0 min-w-0 border-0 p-0" data-testid="crm-clientes-fases">
              <legend className="mb-1.5 p-0 text-sm font-medium">{ROTULO_FASE}</legend>
              <div className="flex flex-wrap gap-2">
                {pastilhas.map(({
                  valor, rotulo, classeCor, numero, escolhida,
                }) => (
                  <label key={valor} htmlFor={`${idFases}-${valor}`} className={CLASSE_PASTILHA}>
                    <input
                      type="radio"
                      id={`${idFases}-${valor}`}
                      name={idFases}
                      value={valor}
                      checked={escolhida}
                      onChange={() => ecra?.escolherFase(valor)}
                      className="h-[18px] w-[18px] shrink-0 accent-primary"
                      data-testid={`crm-clientes-fase-${valor}`}
                    />
                    {classeCor && <span aria-hidden="true" className={classeCor} />}
                    {rotulo}
                    <span className="font-normal tabular-nums">{numero}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>

          <div>
            {/* Sempre na página (mesmo vazio), para os leitores de ecrã lerem o que lá aparecer. */}
            <div aria-live="polite">
              {semResultados && (
                <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed p-6 text-center" data-testid="crm-clientes-sem-resultados">
                  <p className="text-sm text-muted-foreground">{semResultados.texto}</p>
                  {semResultados.limpar && (
                    <Button
                      type="button"
                      variant="outline"
                      className="h-11"
                      onClick={() => {
                        ecra?.limparPesquisa();
                        campoPesquisa.current?.focus();
                      }}
                      data-testid="crm-clientes-limpar"
                    >
                      {TEXTO_LIMPAR_PESQUISA}
                    </Button>
                  )}
                </div>
              )}
            </div>
            {linhas.length > 0 && (
              <ul className="divide-y overflow-hidden rounded-2xl border bg-card" data-testid="crm-clientes-lista">
                {linhas.map((linha) => <LinhaCliente key={linha.id} linha={linha} />)}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
