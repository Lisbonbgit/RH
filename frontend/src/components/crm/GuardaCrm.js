// As guardas das páginas do CRM, nas duas casas (`/crm/*` e `/admin/crm/*`).
// As regras estão em `lib/crm/acesso.js` (com testes); aqui só se ligam às
// rotas, com o `eu` de `useEstadoCrm()` (`GET /api/crm/eu`, uma vez por token).
//
// **A interface só esconde; é o servidor que protege** (`crm/auth.py`). Quem
// não pode entrar e escreve o endereço à mão volta ao início do portal. Se o
// `/eu` não responder, ninguém é recambiado: aparece o aviso com "Tentar de
// novo" (`decisaoGuardaCrm`; revisão da F0/F1).
import React from 'react';
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom';
import { Capacitor } from '@capacitor/core';
import { Button } from '../ui/button';
import { useEstadoCrm } from '../../hooks/useEstadoCrm';
import { MENSAGEM_ACESSO_FALHOU, baseCrm, decisaoGuardaCrm, decisaoSoAdminCrm } from '../../lib/crm/acesso';

/**
 * Enquanto se pergunta ao servidor quem é a pessoa no CRM (ou se carrega uma
 * página). Ocupa o sítio da página e nunca recambia.
 */
export function IndicadorCrm({ texto = 'A carregar o CRM…' }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center p-8" role="status" aria-live="polite">
      <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary motion-reduce:animate-none" aria-hidden="true" />
      <span className="sr-only">{texto}</span>
    </div>
  );
}

/**
 * O `/eu` não respondeu (rede em baixo, backend a reiniciar): não se sabe se a
 * pessoa é membro. Fica onde está, com "Tentar de novo" (volta a perguntar) e
 * "Voltar ao portal" (em `/crm/*` não há outro menu à volta).
 */
export function FalhaAcessoCrm({ tentarDeNovo }) {
  return (
    <div role="alert" className="flex min-h-[40vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <p className="max-w-md text-muted-foreground">{MENSAGEM_ACESSO_FALHOU}</p>
      <div className="flex flex-wrap justify-center gap-2">
        <Button type="button" onClick={tentarDeNovo}>
          Tentar de novo
        </Button>
        <Button asChild variant="outline">
          <Link to="/">Voltar ao portal</Link>
        </Button>
      </div>
    </div>
  );
}

/**
 * A guarda da área do CRM: membro `admin` ou `utilizador`, no browser (nas
 * apps nativas o CRM fica escondido na v1). Com `children` desenha-os (é o
 * que o `CrmLayout` usa, para nem a barra do CRM aparecer a quem não entra);
 * sem eles, é o elemento de uma rota e desenha as filhas (`<Outlet/>`).
 */
export function GuardaCrm({ children }) {
  const estado = useEstadoCrm();
  switch (decisaoGuardaCrm(estado, { nativo: Capacitor.isNativePlatform() })) {
    case 'esperar':
      return <IndicadorCrm />;
    case 'entrar':
      return children ?? <Outlet />;
    case 'falhou':
      return <FalhaAcessoCrm tentarDeNovo={estado.tentarDeNovo} />;
    default:
      return <Navigate to="/" replace />;
  }
}

/**
 * Só para o admin do CRM (as Definições). Os outros membros voltam ao mapa da
 * casa em que estão (`/crm/mapa` ou `/admin/crm/mapa`). Fica sempre dentro da
 * `GuardaCrm`, que já decidiu se a pessoa entra no CRM.
 */
export function SoAdminCrm({ children }) {
  const estado = useEstadoCrm();
  const { pathname } = useLocation();
  switch (decisaoSoAdminCrm(estado)) {
    case 'esperar':
      return <IndicadorCrm />;
    case 'entrar':
      return children ?? <Outlet />;
    case 'falhou':
      return <FalhaAcessoCrm tentarDeNovo={estado.tentarDeNovo} />;
    default:
      return <Navigate to={`${baseCrm(pathname)}/mapa`} replace />;
  }
}

export default GuardaCrm;
