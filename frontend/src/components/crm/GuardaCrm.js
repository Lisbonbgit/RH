// As guardas das páginas do CRM, nas duas casas (`/crm/*` e `/admin/crm/*`).
// As regras estão em `lib/crm/acesso.js` (com testes); aqui só se ligam às
// rotas, com o `eu` de `useEstadoCrm()` (`GET /api/crm/eu`, uma vez por token).
//
// **A interface só esconde; é o servidor que protege** (`crm/auth.py`). Quem
// não pode entrar e escreve o endereço à mão volta ao início do portal.
import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Capacitor } from '@capacitor/core';
import { useEstadoCrm } from '../../hooks/useEstadoCrm';
import { baseCrm, eAdminCrm, podeAbrirAreaCrm } from '../../lib/crm/acesso';

/**
 * Enquanto se pergunta ao servidor quem é a pessoa no CRM (ou se carrega uma
 * página). Ocupa o sítio da página e nunca recambia: uma falha de rede não
 * pode mandar um membro para fora do CRM.
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
 * A guarda da área do CRM: membro `admin` ou `utilizador`, no browser (nas
 * apps nativas o CRM fica escondido na v1). Com `children` desenha-os (é o
 * que o `CrmLayout` usa, para nem a barra do CRM aparecer a quem não entra);
 * sem eles, é o elemento de uma rota e desenha as filhas (`<Outlet/>`).
 */
export function GuardaCrm({ children }) {
  const { carregando, eu } = useEstadoCrm();
  if (carregando) return <IndicadorCrm />;
  if (!podeAbrirAreaCrm(eu, { nativo: Capacitor.isNativePlatform() })) {
    return <Navigate to="/" replace />;
  }
  return children ?? <Outlet />;
}

/**
 * Só para o admin do CRM (as Definições). Os outros membros voltam ao mapa da
 * casa em que estão (`/crm/mapa` ou `/admin/crm/mapa`). Fica sempre dentro da
 * `GuardaCrm`, que já decidiu se a pessoa entra no CRM.
 */
export function SoAdminCrm({ children }) {
  const { carregando, eu } = useEstadoCrm();
  const { pathname } = useLocation();
  if (carregando) return <IndicadorCrm />;
  if (!eAdminCrm(eu)) return <Navigate to={`${baseCrm(pathname)}/mapa`} replace />;
  return children ?? <Outlet />;
}

export default GuardaCrm;
