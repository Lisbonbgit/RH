import React from 'react';
import { Monitor, Sparkles } from 'lucide-react';

// Rota de topo, fora do /admin: é aqui que as lojas vão abrir o Ponto de
// Venda (botão "Iniciar Ponto de Venda" na Faturação, num separador novo).
// Não pode viver dentro do AdminLayout nem exigir o login do portal — a
// funcionária entra com um PIN de 4 dígitos, um mecanismo à parte, já
// construído no backend. Por agora é só o marcador de lugar: a estrutura da
// rota é o que interessa nesta fase; o ecrã de venda vem a seguir.
export default function PosStandalone() {
  return (
    <div className="min-h-screen bg-app-grid flex items-center justify-center p-6">
      <div className="w-full max-w-md text-center animate-fade-in">
        <div className="flex items-center justify-center gap-3 mb-8">
          <div className="h-10 w-10 rounded-xl brand-gradient flex items-center justify-center font-heading font-bold text-white text-xl shadow-lg shadow-primary/30">
            L
          </div>
          <div className="leading-tight text-left">
            <h1 className="font-heading font-bold text-lg">Lisbonb</h1>
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground font-semibold">Ponto de Venda</p>
          </div>
        </div>

        <div className="flex flex-col items-center justify-center text-center py-14 px-6 rounded-2xl border bg-card">
          <div className="h-16 w-16 rounded-2xl brand-gradient text-white flex items-center justify-center shadow-lg shadow-primary/25 mb-5 animate-float">
            <Monitor className="h-8 w-8" />
          </div>
          <h2 className="text-xl md:text-2xl font-heading font-bold flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Ecrã de venda em construção
          </h2>
          <p className="text-muted-foreground mt-3 max-w-sm">
            O Ponto de Venda vai abrir aqui, neste ecrã, com entrada por PIN de
            loja — sem precisar de sessão do portal. Está a ser construído e
            ficará disponível em breve.
          </p>
        </div>
      </div>
    </div>
  );
}
