import React, { useState } from 'react';
import { toast } from 'sonner';
import { Lock, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PosCampoValor from './PosCampoValor';
import { abrirCaixa, detalhesErroPos, eurosPos, temMaisDe2CasasDecimaisPos } from '@/lib/pos';

const formatarData = (isoString) => {
  if (!isoString) return null;
  try {
    const d = new Date(isoString);
    const data = d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit', year: 'numeric' });
    const hora = d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
    return `${data} às ${hora}`;
  } catch (e) {
    return null;
  }
};

// Estado "sem sessão aberta" da caixa (Task 2, do print do Vendus). Quem sai
// daqui é sempre por POST /pos/caixa/abrir com sucesso — nunca há um
// caminho para "entrar sem abrir": sem sessão aberta não há onde registar
// nem um movimento nem uma venda.
export default function PosCaixaFechada({ caixa, ultimoFecho, onAberta }) {
  const [fundo, setFundo] = useState('');
  const [aAbrir, setAAbrir] = useState(false);

  const podeAbrir = fundo !== '' && !temMaisDe2CasasDecimaisPos(fundo) && Number(fundo) >= 0 && !aAbrir;

  const abrir = async () => {
    if (!podeAbrir) return;
    setAAbrir(true);
    try {
      await abrirCaixa({ caixa_id: caixa.id, fundo: Number(fundo) });
      toast.success('Caixa aberta');
      setFundo('');
      onAberta();
    } catch (error) {
      const { mensagem } = detalhesErroPos(error, 'Não foi possível abrir a caixa.');
      toast.error(mensagem);
    } finally {
      setAAbrir(false);
    }
  };

  const dataFecho = formatarData(ultimoFecho?.fechada_em);

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="w-full max-w-md animate-fade-in">
        <div className="flex flex-col items-center text-center rounded-2xl border bg-card p-8">
          <div className="h-16 w-16 rounded-2xl bg-muted text-muted-foreground flex items-center justify-center mb-4">
            <Lock className="h-8 w-8" />
          </div>
          <h2 className="text-xl md:text-2xl font-heading font-bold">Caixa Fechada</h2>
          <p className="text-sm text-muted-foreground mt-1">{caixa?.nome}</p>

          {ultimoFecho && dataFecho ? (
            <div className="w-full mt-6 rounded-xl bg-muted px-4 py-3 text-sm text-muted-foreground">
              Em {dataFecho} · Por {ultimoFecho.fechada_por?.nome || '—'} · Montante: {eurosPos(ultimoFecho.contado)}
            </div>
          ) : (
            <div className="w-full mt-6 rounded-xl bg-muted px-4 py-3 text-sm text-muted-foreground">
              Ainda não há nenhum fecho anterior desta caixa.
            </div>
          )}

          <div className="w-full mt-8 text-left">
            <p className="text-sm text-muted-foreground mb-3">
              Introduza o montante disponível em caixa no momento da abertura (pode ser zero).
            </p>
            <PosCampoValor id="fundo-abertura" label="Montante" valor={fundo} onChange={setFundo} autoFocus disabled={aAbrir} />
          </div>

          <Button size="lg" className="w-full h-14 text-base mt-6" disabled={!podeAbrir} onClick={abrir}>
            {aAbrir ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Abrir Caixa'}
          </Button>
        </div>
      </div>
    </div>
  );
}
