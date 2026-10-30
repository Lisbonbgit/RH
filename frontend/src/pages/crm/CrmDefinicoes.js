// Definições do CRM, só para o admin do CRM (`SoAdminCrm` em `rotasCrm.js`;
// a API recusa os outros com 403). Quatro separadores, cada um com os seus
// pedidos, que carregam e falham sozinhos (os três primeiros são as três
// secções do ecrã "Definições" do CRM autónomo):
//  - Membros (`DefinicoesMembros.js`, T2.29): quem entra no CRM e com que
//    perfil;
//  - Regiões (`DefinicoesRegioes.js`, T2.30): adicionar, mudar o nome,
//    subir/descer e apagar;
//  - Fábrica (`DefinicoesFabrica.js`, T2.30): a morada e o ponto no mapa. É a
//    única com o mapa (o Google Maps), por isso carrega-se à parte, só quando
//    se abre o separador;
//  - Rotas (`DefinicoesRotas.js`, plano F3 T3.41): as horas de cada rota nova
//    e o tempo de serviço de cada paragem nova, por motivo.
// Só o separador aberto existe na página: voltar a um separador pede outra
// vez o que ele mostra.
import React, { Suspense, lazy } from 'react';
import {
  Factory, Map as IconeMapa, Route as IconeRota, Settings, Users,
} from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import { TEXTO_A_CARREGAR_FABRICA } from '../../lib/crm/fabrica';
import DefinicoesMembros from './DefinicoesMembros';
import DefinicoesRegioes from './DefinicoesRegioes';
import DefinicoesRotas from './DefinicoesRotas';

const DefinicoesFabrica = lazy(() => import('./DefinicoesFabrica'));

const CLASSE_SEPARADOR = 'min-h-11 gap-2 px-3 sm:px-4';

export default function CrmDefinicoes() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 animate-fade-in" data-testid="crm-definicoes">
      <PageHeader icon={Settings} title="Definições" subtitle="CRM Purple House" />
      <Tabs defaultValue="membros" className="space-y-4">
        {/* No telemóvel, dois a dois (quatro numa linha não cabem em 375 px); a partir de 640 px, numa linha. */}
        <TabsList className="grid h-auto w-full grid-cols-2 sm:inline-grid sm:w-auto sm:grid-cols-4">
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
          <TabsTrigger value="rotas" className={CLASSE_SEPARADOR} data-testid="crm-separador-rotas">
            <IconeRota className="h-4 w-4" aria-hidden="true" />
            Rotas
          </TabsTrigger>
        </TabsList>
        <TabsContent value="membros" className="mt-0">
          <DefinicoesMembros />
        </TabsContent>
        <TabsContent value="regioes" className="mt-0">
          <DefinicoesRegioes />
        </TabsContent>
        <TabsContent value="fabrica" className="mt-0">
          <Suspense fallback={<IndicadorCrm texto={TEXTO_A_CARREGAR_FABRICA} />}>
            <DefinicoesFabrica />
          </Suspense>
        </TabsContent>
        <TabsContent value="rotas" className="mt-0">
          <DefinicoesRotas />
        </TabsContent>
      </Tabs>
    </div>
  );
}
