import React, { useEffect, useState } from 'react';
import {
  getDefinicoesDeposito, gravarDefinicoesDeposito, getProdutos,
  editarProduto, detalhesErro, temMaisDe2CasasDecimais,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Switch } from '../../../components/ui/switch';
import { Alert, AlertDescription } from '../../../components/ui/alert';
import { Recycle, Loader2, AlertTriangle, Info } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// O valor está na lei (0,10 € por embalagem) e o servidor tem o mesmo por
// omissão. Aqui serve só para o campo abrir preenchido numa conta que ainda
// nunca gravou nada — o número que manda é sempre o que o servidor devolve.
const VALOR_LEGAL = '0.10';

export default function FatDeposito() {
  const [config, setConfig] = useState(null);
  const [valor, setValor] = useState(VALOR_LEGAL);
  const [ref, setRef] = useState('');
  const [produtos, setProdutos] = useState([]);
  const [aCarregar, setACarregar] = useState(true);
  const [aGravar, setAGravar] = useState(false);
  const [erroValor, setErroValor] = useState('');

  useEffect(() => { carregar(); }, []);

  const carregar = async () => {
    setACarregar(true);
    try {
      const [{ data: def }, { data: prods }] = await Promise.all([
        getDefinicoesDeposito(), getProdutos(),
      ]);
      setConfig(def);
      setValor(String(def.valor ?? VALOR_LEGAL));
      setRef(def.vendus_ref || '');
      setProdutos(prods || []);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível ler a configuração.').mensagem);
    } finally {
      setACarregar(false);
    }
  };

  // Grava o que lhe passam e não o que está no estado: um `setConfig` seguido
  // de `gravar()` gravava o valor ANTERIOR, porque o estado do React só chega
  // no render seguinte. É o mesmo tropeço do ecrã do relatório diário.
  const gravar = async (mudancas) => {
    const proximo = {
      ativo: config?.ativo ?? false,
      valor: Number(valor) || 0,
      vendus_ref: ref.trim() || null,
      ...mudancas,
    };
    if (temMaisDe2CasasDecimais(proximo.valor)) {
      setErroValor('Máximo de 2 casas decimais.');
      return;
    }
    if (!(proximo.valor > 0)) {
      setErroValor('O depósito tem de ser maior do que zero.');
      return;
    }
    setErroValor('');
    setAGravar(true);
    try {
      const { data } = await gravarDefinicoesDeposito(proximo);
      setConfig(data);
      setValor(String(data.valor));
      setRef(data.vendus_ref || '');
      toast.success(data.ativo
        ? 'Depósito ligado — as próximas contas passam a cobrá-lo.'
        : 'Depósito desligado. Deixa de ser cobrado.');
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível gravar.').mensagem);
      carregar();
    } finally {
      setAGravar(false);
    }
  };

  const marcar = async (produto, tem) => {
    // Optimista no ecrã e confirmado pelo servidor: marcar oito produtos um a
    // um com meio segundo de espera em cada um é o tipo de ecrã que ninguém
    // acaba de configurar.
    setProdutos((antes) => antes.map(
      (p) => (p.id === produto.id ? { ...p, tem_deposito: tem } : p)));
    try {
      await editarProduto(produto.id, { ...produto, tem_deposito: tem });
    } catch (error) {
      setProdutos((antes) => antes.map(
        (p) => (p.id === produto.id ? { ...p, tem_deposito: !tem } : p)));
      toast.error(detalhesErro(error, 'Não foi possível marcar o produto.').mensagem);
    }
  };

  const marcados = produtos.filter((p) => p.tem_deposito);

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-deposito-page">
      <PageHeader
        icon={Recycle}
        title="Depósito de embalagem"
        subtitle="Faturação · Produtos"
      />

      <Alert className="border-primary/30 bg-accent/40">
        <Info className="h-4 w-4" />
        <AlertDescription className="text-sm">
          Obrigatório desde <strong>10 de abril de 2026</strong>: as embalagens de bebidas
          em <strong>plástico e metal</strong> com menos de 3 litros pagam depósito, que a
          fatura tem de discriminar em linha separada e <strong>sem IVA</strong>.
          O vidro não entra, e os copos do açaí também não — são embalagem de serviço.
          <br />
          <span className="text-muted-foreground">
            O depósito é uma <strong>caução</strong>, não é receita: entra na gaveta e não
            conta na faturação. O Z e o relatório diário dizem-no à parte.
          </span>
        </AlertDescription>
      </Alert>

      {aCarregar ? (
        <div className="flex items-center justify-center h-24">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <Card>
            <CardContent className="p-4 sm:p-5 space-y-5">
              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <p className="font-medium">Cobrar depósito</p>
                  <p className="text-sm text-muted-foreground">
                    {config?.ativo
                      ? `Ligado — as contas com estes ${marcados.length} produtos cobram depósito.`
                      : 'Desligado — não se cobra nada, mesmo com produtos marcados.'}
                  </p>
                </div>
                <Switch
                  checked={!!config?.ativo}
                  disabled={aGravar}
                  onCheckedChange={(v) => gravar({ ativo: v })}
                  data-testid="deposito-ativo-switch"
                />
              </div>

              {config?.ativo && marcados.length === 0 ? (
                <div className="flex items-start gap-2 rounded-lg bg-warning/10 text-warning p-3 text-sm"
                  data-testid="deposito-ligado-sem-produtos">
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                  <span>
                    Está ligado mas nenhum produto está marcado — não se cobra depósito
                    nenhum. Marque as águas e os refrigerantes aqui em baixo.
                  </span>
                </div>
              ) : null}

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="deposito-valor">Valor por embalagem</Label>
                  <Input
                    id="deposito-valor" type="number" step="0.01" min="0.01"
                    value={valor}
                    onChange={(e) => { setValor(e.target.value); setErroValor(''); }}
                    onBlur={() => gravar({})}
                    disabled={aGravar}
                    aria-invalid={!!erroValor}
                    data-testid="deposito-valor-input"
                  />
                  {erroValor
                    ? <p className="text-xs text-destructive">{erroValor}</p>
                    : <p className="text-xs text-muted-foreground">
                        A lei fixa 0,10 €. Só se muda se a lei mudar.
                      </p>}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="deposito-ref">Artigo no Vendus</Label>
                  <Input
                    id="deposito-ref" value={ref}
                    onChange={(e) => setRef(e.target.value)}
                    onBlur={() => gravar({})}
                    placeholder="345983786"
                    disabled={aGravar}
                    data-testid="deposito-ref-input"
                  />
                  <p className="text-xs text-muted-foreground">
                    Sem isto o Vendus cria um artigo novo a cada venda. Está em
                    Produtos → Depósitos, no backoffice deles.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 sm:p-5 space-y-4">
              <div>
                <p className="font-medium">Que produtos cobram depósito</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Só as embalagens abrangidas. <strong>Esta lista tem de ser igual à do
                  Vendus</strong> (Produtos → Depósitos): a app L'Açaí fatura pela mesma
                  conta e usa a lista de lá.
                </p>
              </div>

              <div className="divide-y rounded-md border" data-testid="deposito-produtos">
                {produtos.length === 0 ? (
                  <p className="p-6 text-sm text-muted-foreground text-center">
                    Sem produtos no catálogo.
                  </p>
                ) : produtos.map((produto) => (
                  <div key={produto.id}
                    className="flex items-center justify-between gap-3 px-3 py-2.5"
                    data-testid={`deposito-produto-${produto.id}`}>
                    <span className="text-sm truncate">
                      {produto.nome}
                      {produto.ativo === false
                        ? <span className="text-muted-foreground"> · inativo</span>
                        : null}
                    </span>
                    <Switch
                      checked={!!produto.tem_deposito}
                      onCheckedChange={(v) => marcar(produto, v)}
                      aria-label={`Depósito em ${produto.nome}`}
                      data-testid={`deposito-marca-${produto.id}`}
                    />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
