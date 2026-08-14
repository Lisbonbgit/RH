import React from 'react';
import { CreditCard } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';

export default function FatPagamentos() {
  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-pagamentos-page">
      <PageHeader icon={CreditCard} title="Tipos de Pagamento" subtitle="Meios de pagamento aceites e os seus códigos fiscais" />
    </div>
  );
}
