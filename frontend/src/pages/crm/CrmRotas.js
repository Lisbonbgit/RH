// As rotas, em `rotas` (F3 / T3.35: "Brevemente"; a lista dos dias e a escolha
// do dia chegam na T3.37). Existe já para o item "Rotas" do menu ter página e o
// `React.lazy` do `rotasCrm.js` ter o que carregar.
import React from 'react';
import { Route as IconeRota } from 'lucide-react'; // nunca `Route`: confundia-se com o `Route` do React Router
import ComingSoon from '../../components/ComingSoon';

export default function CrmRotas() {
  return (
    <ComingSoon
      icon={IconeRota}
      title="Rotas"
      subtitle="CRM Purple House"
      note="A escolha do dia e as rotas próximas e anteriores, com o estado e o número de paragens de cada uma."
    />
  );
}
