import React from 'react';
import { Store } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';

export default function FatLojas() {
  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-lojas-page">
      <PageHeader icon={Store} title="Lojas e Caixas" subtitle="Lojas de faturação e as caixas de cada uma" />
    </div>
  );
}
