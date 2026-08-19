import React from 'react';
import { useLocation } from 'react-router-dom';
import { Card, CardContent } from '../../../components/ui/card';
import { Clock } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';

// Secções do Estoque no portal RH que ainda vão ser ligadas (movimentos,
// lista de compras, transferências, histórico). Mostram um aviso, como no
// portal do próprio Estoque.
const NOMES = {
  escanear: 'Escanear',
  'lista-compras': 'Lista de compras',
  transferencias: 'Transferências',
  historico: 'Histórico',
};

export default function EstoqueEmBreve() {
  const { pathname } = useLocation();
  const nome = NOMES[pathname.split('/').pop()] || 'Esta secção';
  return (
    <div className="space-y-6">
      <PageHeader title={`Estoque · ${nome}`} subtitle="Secção do Estoque no portal de gestão." />
      <Card>
        <CardContent className="flex flex-col items-center text-center gap-3 py-16">
          <div className="h-12 w-12 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
            <Clock className="h-6 w-6" />
          </div>
          <p className="text-base font-medium">“{nome}” está a chegar</p>
          <p className="text-sm text-muted-foreground max-w-sm">
            Esta secção entra numa próxima fase da integração com o Estoque. O Stock e as Faturas já funcionam.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
