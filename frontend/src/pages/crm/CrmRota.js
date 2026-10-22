// O planeador da rota de um dia, em `rotas/:data` (F3 / T3.35: "Brevemente";
// o planeador chega nas T3.38–T3.39, com o `criarPlaneador` do
// `lib/crm/planeador.js`).
//
// Com um dia que existe, a rota abre na área toda, sem as margens do layout
// (`ecraCheioDoCrm`), porque o planeador é mapa e painel. Enquanto é só o
// aviso, é ele que põe as margens de sempre e desce sozinho; com um dia que não
// existe o layout já as põe.
import React from 'react';
import { useLocation } from 'react-router-dom';
import { Route as IconeRota } from 'lucide-react'; // nunca `Route`: confundia-se com o `Route` do React Router
import ComingSoon from '../../components/ComingSoon';
import { ecraCheioDoCrm } from '../../lib/crm/acesso';

export default function CrmRota() {
  const { pathname } = useLocation();
  const cheio = ecraCheioDoCrm(pathname);
  return (
    <div className={cheio ? 'h-full overflow-y-auto p-4 md:p-6 lg:p-8' : undefined}>
      <ComingSoon
        icon={IconeRota}
        title="Planear rota"
        subtitle="CRM Purple House"
        note="O mapa com as paragens numeradas e a linha da rota, a ordem, as horas de chegada e o regresso, as sugestões perto e Guardar rota."
      />
    </div>
  );
}
