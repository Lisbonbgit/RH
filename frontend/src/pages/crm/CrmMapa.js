// Mapa das lojas (F1: "Brevemente"; o mapa chega na F2, com o Leaflet).
//
// A rota do mapa abre em área cheia, sem as margens do layout
// (`ecraCheioDoCrm`), porque o mapa as dispensa. Enquanto é só o aviso, é ele
// que põe as margens de sempre.
import React from 'react';
import { Map as IconeMapa } from 'lucide-react'; // nunca `Map`: tapava o Map do JavaScript
import ComingSoon from '../../components/ComingSoon';

export default function CrmMapa() {
  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 lg:p-8">
      <ComingSoon
        icon={IconeMapa}
        title="Mapa"
        subtitle="CRM Purple House"
        note="As lojas no mapa, com a cor da fase e o nome sempre à vista, filtros por fase e por região, e o cartão de cada loja com Ligar e Ver ficha."
      />
    </div>
  );
}
