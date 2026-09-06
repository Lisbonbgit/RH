import React, { useCallback, useEffect, useState } from 'react';
import { getDescontoStock, mudarDescontoStock, detalhesErro } from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { PackageMinus, AlertTriangle, Loader2 } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

/**
 * **O interruptor do desconto automático de stock.**
 *
 * Desligado quer dizer que as gramagens escritas nas personalizações só
 * servem para o relatório de Consumo. Ligado quer dizer que cada fatura tira
 * do armazém o que o copo gastou.
 *
 * O ecrã existe para tornar visível o que decide se ligá-lo faz sentido hoje:
 * as lojas que ainda não estão ligadas a uma unidade do Estoque. Ligar com
 * lojas por ligar não dá erro nenhum — o stock dessas simplesmente não desce,
 * e a diferença só aparece na contagem do mês.
 */
export default function FatDescontoStock() {
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [aGuardar, setAGuardar] = useState(false);
  const [erro, setErro] = useState('');

  const ler = useCallback(async () => {
    setCarregando(true);
    try {
      const { data } = await getDescontoStock();
      setDados(data);
      setErro('');
    } catch (error) {
      const { mensagem } = detalhesErro(error, 'Não foi possível ler o estado do desconto.');
      setErro(mensagem);
      setDados(null);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { ler(); }, [ler]);

  const mudar = async (ativo) => {
    setAGuardar(true);
    try {
      const { data } = await mudarDescontoStock(ativo);
      setDados(data);
      toast.success(ativo ? 'O stock passa a descer com as vendas.'
        : 'O stock deixou de descer automaticamente.');
    } catch (error) {
      const { mensagem } = detalhesErro(error, 'Não foi possível mudar o interruptor.');
      toast.error(mensagem);
    } finally {
      setAGuardar(false);
    }
  };

  const porLigar = dados?.lojas_por_ligar || [];

  return (
    <div className="space-y-6">
      <PageHeader
        icon={PackageMinus}
        title="Desconto de stock"
        subtitle="Se cada fatura tira do armazém o que o copo gastou"
      />

      {erro && (
        <div className="flex items-start gap-2 rounded-lg bg-destructive/10 text-destructive p-3 text-sm"
          data-testid="desconto-erro">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{erro}</span>
        </div>
      )}

      <Card>
        <CardContent className="p-5 flex items-start justify-between gap-6">
          <div className="space-y-1 min-w-0">
            <p className="font-medium">Descontar stock a cada venda</p>
            <p className="text-sm text-muted-foreground">
              Desligado, as gramagens escritas nas personalizações servem só para o
              relatório de Consumo. Ligado, cada fatura emitida tira do armazém o que
              foi ao copo — e as devoluções não repõem nada, por decisão.
            </p>
          </div>
          {/* **Caixa nativa e não o `Switch` do desenho**, e é uma escolha
              deliberada num controlo só: o `Switch` responde a eventos de
              ponteiro que o arnês de testes deste repositório não tem, e este
              é o botão que põe o stock de cinco lojas a mexer — não pode ser
              o único do módulo que ninguém consegue carregar num teste. Traz
              de graça o teclado e o leitor de ecrã. */}
          {carregando ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground shrink-0" />
          ) : (
            <label className="flex items-center gap-2 shrink-0 cursor-pointer">
              <input
                type="checkbox"
                className="h-5 w-5 accent-primary cursor-pointer"
                checked={!!dados?.ativo}
                disabled={aGuardar || !dados}
                onChange={(e) => mudar(e.target.checked)}
                data-testid="desconto-interruptor"
              />
              <span className="text-sm font-medium">
                {dados?.ativo ? 'Ligado' : 'Desligado'}
              </span>
            </label>
          )}
        </CardContent>
      </Card>

      {/* O que decide se ligar isto faz sentido hoje. Uma loja por ligar não
          dá erro nenhum: o stock dela não desce, e ninguém dá por isso. */}
      {porLigar.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-400 p-3 text-sm"
          data-testid="desconto-lojas-por-ligar">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>
            <strong>{porLigar.length} loja(s) ainda sem unidade do Estoque</strong> —{' '}
            {porLigar.map((l) => l.nome).join(', ')}. Enquanto assim for, o stock destas
            não desce e não aparece erro nenhum. Escolhe-se a unidade em
            Configuração → Lojas e Caixas.
          </span>
        </div>
      )}

      {dados && !carregando && porLigar.length === 0 && (
        <p className="text-xs text-muted-foreground" data-testid="desconto-tudo-ligado">
          Todas as lojas activas estão ligadas a uma unidade do Estoque.
        </p>
      )}

      <div className="rounded-lg border p-4 text-sm text-muted-foreground space-y-2">
        <p className="font-medium text-foreground">Antes de ligar</p>
        <p>
          Compare um período do relatório de <strong>Consumo</strong> com uma contagem
          real do armazém. É a única forma de saber se as gramagens escritas batem com
          o que desaparece — e uma gramagem errada com isto ligado faz o stock mentir
          sem ninguém dar por isso até ao fim do mês.
        </p>
        <p>
          As vendas da <strong>app</strong> nunca descontam: entram como documentos do
          Vendus, sem as personalizações escolhidas. O stock vai ficar sempre um pouco
          mais alto do que a realidade nessa medida.
        </p>
      </div>
    </div>
  );
}
