import React from 'react';
import PageHeader from './PageHeader';
import { Hammer, Sparkles } from 'lucide-react';

// Página placeholder para módulos ainda por construir (ex.: Financeiro, Marketing)
export default function ComingSoon({ icon, title = 'Módulo', subtitle = 'Em construção', note }) {
  return (
    <div className="space-y-6 animate-fade-in" data-testid="coming-soon-page">
      <PageHeader icon={icon || Hammer} title={title} subtitle={subtitle} />
      <div className="flex flex-col items-center justify-center text-center py-16 md:py-24 rounded-2xl border bg-card">
        <div className="h-16 w-16 rounded-2xl brand-gradient text-white flex items-center justify-center shadow-lg shadow-primary/25 mb-5 animate-float">
          <Sparkles className="h-8 w-8" />
        </div>
        <h3 className="text-xl md:text-2xl font-heading font-bold">Brevemente</h3>
        <p className="text-muted-foreground mt-2 max-w-md px-4">
          {note || 'Este módulo está a ser construído e ficará disponível em breve no portal Gestão Lisbonb.'}
        </p>
      </div>
    </div>
  );
}
