// Definições do CRM, só para o admin do CRM (`SoAdminCrm` em `rotasCrm.js`;
// a API recusa os outros com 403). Três separadores (plano T2.29), cada um
// com os seus pedidos, que carregam e falham sozinhos, como as três secções
// do ecrã "Definições" do CRM autónomo:
//  - Membros (`DefinicoesMembros.js`, T2.29): quem entra no CRM e com que
//    perfil;
//  - Regiões e Fábrica: chegam na T2.30 (até lá, "Brevemente").
// Só o separador aberto existe na página: voltar a um separador pede outra
// vez o que ele mostra.
import React from 'react';
import { Factory, Map as IconeMapa, Settings, Users } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import DefinicoesMembros from './DefinicoesMembros';

const CLASSE_SEPARADOR = 'min-h-11 gap-2 px-3 sm:px-4';

function Brevemente({ texto }) {
  return (
    <div className="rounded-2xl border bg-card p-8 text-center">
      <p className="font-heading text-lg font-semibold">Brevemente</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{texto}</p>
    </div>
  );
}

export default function CrmDefinicoes() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 animate-fade-in" data-testid="crm-definicoes">
      <PageHeader icon={Settings} title="Definições" subtitle="CRM Purple House" />
      <Tabs defaultValue="membros" className="space-y-4">
        <TabsList className="grid h-auto w-full grid-cols-3 sm:inline-grid sm:w-auto">
          <TabsTrigger value="membros" className={CLASSE_SEPARADOR} data-testid="crm-separador-membros">
            <Users className="h-4 w-4" aria-hidden="true" />
            Membros
          </TabsTrigger>
          <TabsTrigger value="regioes" className={CLASSE_SEPARADOR} data-testid="crm-separador-regioes">
            <IconeMapa className="h-4 w-4" aria-hidden="true" />
            Regiões
          </TabsTrigger>
          <TabsTrigger value="fabrica" className={CLASSE_SEPARADOR} data-testid="crm-separador-fabrica">
            <Factory className="h-4 w-4" aria-hidden="true" />
            Fábrica
          </TabsTrigger>
        </TabsList>
        <TabsContent value="membros" className="mt-0">
          <DefinicoesMembros />
        </TabsContent>
        <TabsContent value="regioes" className="mt-0">
          <Brevemente texto="As regiões do mapa: adicionar, mudar o nome, ordenar e apagar." />
        </TabsContent>
        <TabsContent value="fabrica" className="mt-0">
          <Brevemente texto="A morada e o ponto da fábrica no mapa." />
        </TabsContent>
      </Tabs>
    </div>
  );
}
