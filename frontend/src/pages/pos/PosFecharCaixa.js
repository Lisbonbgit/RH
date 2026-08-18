import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, AlertTriangle, HelpCircle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import PosCampoValor from './PosCampoValor';
import { fecharCaixa, detalhesErroPos, temMaisDe2CasasDecimaisPos } from '@/lib/pos';

const euros = (valor) => `€ ${(Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function LinhaValor({ label, valor, destaque }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className={destaque ? 'font-heading font-bold text-lg' : 'font-medium'}>{valor}</span>
    </div>
  );
}

// Fechar a caixa e o relatório Z (Task 2, spec §7.6). Regra 3 do dono: o
// fecho NUNCA bloqueia por a contagem não bater, nem por a verificação
// contra o Vendus falhar — os dois casos só mostram um aviso, a funcionária
// segue para casa à mesma. Duas etapas: contar (envia `contado`) e depois
// o resultado (o que o servidor devolveu, incluindo o Z) — nunca calculado
// aqui, sempre o número que veio de faturacao/caixa.py::fechar_caixa.
export default function PosFecharCaixa({ aberto, onFechar, caixa, sessao, onFechado }) {
  const [contado, setContado] = useState('');
  const [aEnviar, setAEnviar] = useState(false);
  const [resultado, setResultado] = useState(null);

  useEffect(() => {
    if (aberto) { setContado(''); setResultado(null); }
  }, [aberto]);

  const podeFechar = contado !== '' && !temMaisDe2CasasDecimaisPos(contado) && Number(contado) >= 0 && !aEnviar;

  const confirmarContagem = async () => {
    if (!podeFechar) return;
    setAEnviar(true);
    try {
      const { data } = await fecharCaixa({ caixa_id: caixa.id, contado: Number(contado) });
      setResultado(data);
    } catch (error) {
      const { mensagem } = detalhesErroPos(error, 'Não foi possível fechar a caixa.');
      toast.error(mensagem);
    } finally {
      setAEnviar(false);
    }
  };

  const concluir = () => {
    setResultado(null);
    onFechado();
  };

  return (
    <Dialog open={aberto} onOpenChange={(v) => { if (!v && !resultado) onFechar(); }}>
      <DialogContent className="max-w-md">
        {!resultado ? (
          <>
            <DialogHeader><DialogTitle>Fechar Caixa</DialogTitle></DialogHeader>
            <p className="text-sm text-muted-foreground">
              Conte o dinheiro na gaveta e introduza o montante contado. O esperado e a
              diferença aparecem a seguir — a contagem nunca impede o fecho.
            </p>
            <div className="py-2">
              <PosCampoValor id="contado-fecho" label="Montante contado" valor={contado} onChange={setContado} autoFocus disabled={aEnviar} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={onFechar} disabled={aEnviar}>Cancelar</Button>
              <Button onClick={confirmarContagem} disabled={!podeFechar}>
                {aEnviar ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Fechar Caixa'}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader><DialogTitle>Relatório Z</DialogTitle></DialogHeader>
            <div className="divide-y">
              <LinhaValor label="Fundo de abertura" valor={euros(resultado.fundo)} />
              <LinhaValor label="Vendas em dinheiro" valor={euros(resultado.vendas_dinheiro)} />
              <LinhaValor label="Entradas" valor={euros(resultado.entradas)} />
              <LinhaValor label="Saídas" valor={euros(resultado.saidas)} />
              <LinhaValor label="Esperado" valor={euros(resultado.esperado)} destaque />
              <LinhaValor label="Contado" valor={euros(resultado.contado)} destaque />
              <LinhaValor
                label="Diferença"
                valor={`${resultado.diferenca > 0 ? '+' : ''}${euros(resultado.diferenca)}`}
                destaque
              />
            </div>

            <Separator />

            {resultado.verificacao_vendus?.aviso && (
              <div className="flex items-start gap-2 rounded-lg bg-warning/10 text-warning p-3 text-sm">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>{resultado.verificacao_vendus.aviso}</span>
              </div>
            )}
            {resultado.verificacao_vendus?.nao_verificado && (
              <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <HelpCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>Não foi possível verificar contra o Vendus. {resultado.verificacao_vendus.nao_verificado}</span>
              </div>
            )}
            {!resultado.verificacao_vendus && (
              <div className="flex items-start gap-2 rounded-lg bg-success/10 p-3 text-sm">
                <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-success" />
                <span>Confere com o Vendus.</span>
              </div>
            )}

            <DialogFooter>
              <Button className="w-full h-12" onClick={concluir}>Concluir</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
