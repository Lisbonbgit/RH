import React from 'react';
import { Users } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';

export default function FatUtilizadores() {
  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-utilizadores-page">
      <PageHeader icon={Users} title="Utilizadores" subtitle="Quem pode faturar, com PIN e estado" />
    </div>
  );
}
