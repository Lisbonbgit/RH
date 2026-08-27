import React, { useEffect, useState } from 'react';
import { estadoDoModoLido } from '../../../lib/pos';
import {
  getModoDeEmissaoDoBackoffice, mudarModoDeEmissao, detalhesErro,
} from '../../../lib/faturacao';
import FatModoDeEmissao from './FatModoDeEmissao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { ShieldCheck, GraduationCap, Loader2, AlertTriangle } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// **A palavra que se escreve para passar a faturar a sério.**
//
// Um botão de confirmação («tem a certeza?») responde-se com um toque
// distraído; escrever uma palavra não. É a única coisa neste portal que faz
// uma fatura chegar à Autoridade Tributária em nome da Fordaimon Foods, e o
// caminho para lá tem de custar mais do que o caminho de volta.
//
// Voltar a testes NÃO pede nada: é o travão, e um travão que se discute é um
// travão que não se usa com o cliente à frente.
const PALAVRA = 'FATURAR';

export default function FatTrocarModo() {
  const [estado, setEstado] = useState(undefined);
  const [escrito, setEscrito] = useState('');
  const [aMudar, setAMudar] = useState(false);
  // Muda ao trocar de modo, para o `key` remontar a faixa e ela reler o
  // servidor — em vez de eu lhe passar o valor por fora e ficar com duas
  // verdades sobre a mesma coisa no mesmo ecrã.
  const [versao, setVersao] = useState(0);

  const ler = () => estadoDoModoLido(getModoDeEmissaoDoBackoffice).then(setEstado);
  useEffect(() => { ler(); }, []);

  const mudar = async (modo) => {
    setAMudar(true);
    try {
      await mudarModoDeEmissao(modo);
      setEscrito('');
      setVersao((v) => v + 1);
      await ler();
      toast.success(modo === 'normal'
        ? 'A faturar a sério. As próximas faturas vão para a Autoridade Tributária.'
        : 'De volta ao modo de formação. As faturas deixam de ter valor fiscal.');
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível mudar o modo.').mensagem);
      await ler();
    } finally {
      setAMudar(false);
    }
  };

  const aSerio = estado === 'normal';
  const podeArrancar = escrito.trim().toUpperCase() === PALAVRA;

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-trocar-modo-page">
      <PageHeader
        icon={ShieldCheck}
        title="Modo de emissão"
        subtitle="Faturação · Configuração"
      />

      {/* A MESMA faixa que o dono vê no painel e a operadora vê no balcão. Um
          segundo desenho aqui era uma segunda verdade sobre o mesmo estado. */}
      <FatModoDeEmissao key={versao} />

      {estado === undefined ? (
        <div className="flex items-center justify-center h-24">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : aSerio ? (
        <Card>
          <CardContent className="p-4 sm:p-5 space-y-4">
            <div>
              <p className="font-medium flex items-center gap-2">
                <GraduationCap className="h-4 w-4 text-muted-foreground" />
                Voltar ao modo de formação
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                As faturas emitidas a partir daqui deixam de ter valor fiscal e servem para
                treinar. <strong>As que já saíram continuam reais</strong> — essas só se
                corrigem com uma nota de crédito.
              </p>
            </div>
            <Button
              type="button" variant="outline" onClick={() => mudar('tests')}
              disabled={aMudar} data-testid="voltar-a-testes-btn"
            >
              {aMudar ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              Voltar ao modo de formação
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-destructive/40">
          <CardContent className="p-4 sm:p-5 space-y-4">
            <div>
              <p className="font-medium flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-destructive" />
                Passar a faturar a sério
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                A partir do momento em que carregar, cada fatura emitida em qualquer POS
                emparelhado é <strong>real</strong>, entra na contabilidade da Fordaimon Foods e
                chega à Autoridade Tributária. Não se apaga nenhuma.
              </p>
              <p className="text-sm text-muted-foreground mt-2">
                Antes de continuar, confirme em <strong>Dispositivos</strong> que só estão
                emparelhados os PC que vão mesmo trabalhar — o modo é um só para todas as lojas.
              </p>
            </div>

            <div className="space-y-2 max-w-sm">
              <Label htmlFor="palavra-de-confirmacao">
                Para confirmar, escreva <code className="font-semibold">{PALAVRA}</code>
              </Label>
              <Input
                id="palavra-de-confirmacao"
                value={escrito}
                onChange={(e) => setEscrito(e.target.value)}
                autoComplete="off"
                placeholder={PALAVRA}
                disabled={aMudar}
                data-testid="palavra-de-confirmacao"
              />
            </div>

            <Button
              type="button"
              onClick={() => mudar('normal')}
              disabled={!podeArrancar || aMudar}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              data-testid="passar-a-normal-btn"
            >
              {aMudar ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              Passar a faturar a sério
            </Button>
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground">
        Quem mudar o modo fica registado com o seu email e a hora. O POS relê o estado sozinho,
        de minuto a minuto — a faixa do balcão muda sem ninguém ter de recarregar o ecrã.
      </p>
    </div>
  );
}
