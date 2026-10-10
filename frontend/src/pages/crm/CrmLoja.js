// Ficha da loja, em `lojas/:lojaId` (F1: "Brevemente"; a ficha chega na F2).
import React from 'react';
import { Store } from 'lucide-react';
import ComingSoon from '../../components/ComingSoon';

export default function CrmLoja() {
  return (
    <ComingSoon
      icon={Store}
      title="Ficha da loja"
      subtitle="CRM Purple House"
      note="Os dados da loja, a fase num toque, o horário de receção e os dias em que está fechada."
    />
  );
}
