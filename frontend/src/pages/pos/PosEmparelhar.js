import React, { useState } from 'react';
import { toast } from 'sonner';
import { Store, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { emparelhar, guardarDispositivo, detalhesErroPos } from '@/lib/pos';

// Estado 1 da máquina de estados do POS (PosApp): sem token de dispositivo.
// Um único campo grande para colar o código de 8 caracteres que o gestor
// gera no backoffice (POST /faturacao/dispositivos-pos) — o próprio PC troca
// esse código pelo seu token de dispositivo aqui. Sem Depends nenhum do lado
// do servidor: é o bootstrap da cadeia (ver faturacao/pos_auth.py::emparelhar).
export default function PosEmparelhar({ onEmparelhado }) {
  const [codigo, setCodigo] = useState('');
  const [aEnviar, setAEnviar] = useState(false);

  const submeter = async (e) => {
    e.preventDefault();
    const limpo = codigo.trim();
    if (!limpo) { toast.error('Cole ou escreva o código de emparelhamento.'); return; }
    setAEnviar(true);
    try {
      const { data } = await emparelhar(limpo);
      guardarDispositivo(data);
      toast.success(data.loja_nome ? `Emparelhado com ${data.loja_nome}` : 'Dispositivo emparelhado');
      onEmparelhado({ token: data.device_token, lojaId: data.loja_id, lojaNome: data.loja_nome });
    } catch (error) {
      const { mensagem } = detalhesErroPos(error, 'Não foi possível emparelhar este PC.');
      toast.error(mensagem);
    } finally {
      setAEnviar(false);
    }
  };

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

        <form onSubmit={submeter} className="flex flex-col items-center text-center py-12 px-6 sm:px-10 rounded-2xl border bg-card">
          <div className="h-16 w-16 rounded-2xl brand-gradient text-white flex items-center justify-center shadow-lg shadow-primary/25 mb-5">
            <Store className="h-8 w-8" />
          </div>
          <h2 className="text-xl md:text-2xl font-heading font-bold">Emparelhar este PC</h2>
          <p className="text-muted-foreground mt-2 mb-8 max-w-sm">
            Peça ao gestor o código de emparelhamento gerado para esta loja e
            escreva-o (ou cole-o) abaixo.
          </p>

          <div className="w-full text-left space-y-2">
            <Label htmlFor="codigo-emparelhamento">Código de emparelhamento</Label>
            <Input
              id="codigo-emparelhamento"
              value={codigo}
              onChange={(e) => setCodigo(e.target.value.toUpperCase())}
              placeholder="Ex.: A1B2C3D4"
              autoFocus
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              disabled={aEnviar}
              className="h-16 text-center text-2xl md:text-3xl font-mono tracking-[0.3em] uppercase"
            />
          </div>

          <Button type="submit" size="lg" className="w-full h-14 text-base mt-8" disabled={aEnviar}>
            {aEnviar ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Emparelhar'}
          </Button>
        </form>
      </div>
    </div>
  );
}
