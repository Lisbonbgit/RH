import React from 'react';

/**
 * Cabeçalho da marca reutilizável para as páginas de admin.
 * Mantém coerência visual com o hero do dashboard (azul/turquesa).
 *
 * Props:
 *  - icon: componente de ícone (lucide-react)
 *  - title: string
 *  - subtitle: string | opcional
 *  - children: ações à direita (botões, navegação) | opcional
 */
export default function PageHeader({ icon: Icon, title, subtitle, children }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border bg-card p-5 md:p-6 flex flex-wrap items-center justify-between gap-4">
      <div className="absolute inset-y-0 left-0 w-1.5 brand-gradient" />
      <div className="flex items-center gap-4 min-w-0">
        {Icon && (
          <div className="h-12 w-12 rounded-xl brand-gradient text-white flex items-center justify-center shadow-lg shadow-primary/25 shrink-0">
            <Icon className="h-6 w-6" />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-2xl md:text-3xl font-heading font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="text-muted-foreground mt-0.5 text-sm">{subtitle}</p>}
        </div>
      </div>
      {/* Controlos: quebram linha de forma ordenada quando não cabem ao lado do título. */}
      {children && <div className="flex flex-wrap items-center gap-2 max-w-full">{children}</div>}
    </div>
  );
}
