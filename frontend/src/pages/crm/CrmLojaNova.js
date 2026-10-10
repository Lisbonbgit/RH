// Nova loja (F1: "Brevemente"; o formulário chega na F2).
import React from 'react';
import { MapPinPlus } from 'lucide-react';
import ComingSoon from '../../components/ComingSoon';

export default function CrmLojaNova() {
  return (
    <ComingSoon
      icon={MapPinPlus}
      title="Nova loja"
      subtitle="CRM Purple House"
      note="Registar uma loja: primeiro o sítio (pino no mapa, morada ou «Estou nesta loja»), depois o nome, a fase e os contactos."
    />
  );
}
