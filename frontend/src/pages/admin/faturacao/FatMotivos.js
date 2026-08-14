import React from 'react';
import { FileMinus } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';

export default function FatMotivos() {
  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-motivos-page">
      <PageHeader icon={FileMinus} title="Motivos de NC" subtitle="Motivos de nota de crédito disponíveis na faturação" />
    </div>
  );
}
