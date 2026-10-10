// Definições do CRM, só para o admin do CRM (`SoAdminCrm` em `rotasCrm.js`).
// F1: "Brevemente"; os separadores Membros, Regiões e Fábrica chegam na F2.
import React from 'react';
import { Settings } from 'lucide-react';
import ComingSoon from '../../components/ComingSoon';

export default function CrmDefinicoes() {
  return (
    <ComingSoon
      icon={Settings}
      title="Definições"
      subtitle="CRM Purple House"
      note="Quem entra no CRM e com que perfil, as regiões e o ponto da fábrica."
    />
  );
}
