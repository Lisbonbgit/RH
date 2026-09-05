import React, { useCallback, useEffect, useState } from 'react';
import { getConsumo, getLojas, detalhesErro } from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Scale, Search, Loader2, AlertTriangle, Link2Off } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// As mesmas datas dos Relatórios, e de propósito: o dono compara os dois
// ecrãs lado a lado, e dois defaults diferentes davam períodos diferentes
// sem ninguém reparar.
const hoje = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Lisbon' });
const primeiroDoMes = () => hoje().slice(0, 8) + '01';

// Três casas: é a resolução com que as gramagens se escrevem (30 g = 0,03 kg)
// e o mínimo para uma pitada não desaparecer da tabela.
const numero = (v) => Number(v || 0).toLocaleString('pt-PT', {
  minimumFractionDigits: 0, maximumFractionDigits: 3,
});

/**
 * **O que saiu do armazém** — o relatório que dá sentido às gramagens.
 *
 * Não desconta nada: soma o que as personalizações escolhidas dizem gastar,
 * para se poder comparar com uma contagem real antes de haver desconto
 * automático nenhum. Uma gramagem errada com o desconto já ligado faz o stock
 * mentir com autoridade, e isso só se descobre ao fim do mês.
 */
export default function FatConsumo() {
  const [filtros, setFiltros] = useState({ de: primeiroDoMes(), ate: hoje(), loja_id: 'todas' });
  const [lojas, setLojas] = useState([]);
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState('');

  useEffect(() => {
    getLojas().then(({ data }) => setLojas(data || [])).catch(() => setLojas([]));
  }, []);

  const procurar = useCallback(async () => {
    setCarregando(true);
    setErro('');
    try {
      const { data } = await getConsumo({
        de: filtros.de,
        ate: filtros.ate,
        ...(filtros.loja_id !== 'todas' ? { loja_id: filtros.loja_id } : {}),
      });
      setDados(data);
    } catch (error) {
      const { mensagem } = detalhesErro(error, 'Não foi possível ler o consumo.');
      setErro(mensagem);
      toast.error(mensagem);
    } finally {
      setCarregando(false);
    }
  }, [filtros]);

  useEffect(() => { procurar(); /* eslint-disable-next-line */ }, []);

  const linhas = dados?.linhas || [];
  const porLigar = linhas.filter((l) => !l.ligado_ao_estoque).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Faturação · Consumo"
        subtitle="O que saiu do armazém, somado a partir das personalizações vendidas."
        icon={Scale}
      />

      <Card>
        <CardContent className="p-4 grid gap-3 md:grid-cols-4 items-end">
          <div className="space-y-1">
            <Label htmlFor="consumo-de">De</Label>
            <Input id="consumo-de" type="date" value={filtros.de}
              onChange={(e) => setFiltros({ ...filtros, de: e.target.value })}
              data-testid="consumo-de" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="consumo-ate">Até</Label>
            <Input id="consumo-ate" type="date" value={filtros.ate}
              onChange={(e) => setFiltros({ ...filtros, ate: e.target.value })}
              data-testid="consumo-ate" />
          </div>
          <div className="space-y-1">
            <Label>Loja</Label>
            <Select value={filtros.loja_id}
              onValueChange={(v) => setFiltros({ ...filtros, loja_id: v })}>
              <SelectTrigger data-testid="consumo-loja"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todas">Todas as lojas</SelectItem>
                {lojas.map((l) => <SelectItem key={l.id} value={l.id}>{l.nome}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={procurar} disabled={carregando} data-testid="consumo-procurar">
            {carregando ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Search className="h-4 w-4 mr-2" />}
            Ver
          </Button>
        </CardContent>
      </Card>

      {erro && (
        <div className="flex items-start gap-2 rounded-lg bg-destructive/10 text-destructive p-3 text-sm"
          data-testid="consumo-erro">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{erro}</span>
        </div>
      )}

      {/* **As vendas da app, ditas e não escondidas.**

          A app não manda os toppings ao Vendus, portanto o documento não os
          tem e não os pode ter. Um relatório que as somasse como zero dizia
          «a app não gasta granola» — falso, e com ar de verdade. Enquanto a
          porta de leitura do lado da app não existir, o que se pode fazer é
          dizer quantas vendas ficaram de fora. */}
      {dados && dados.documentos_da_app > 0 && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-400 p-3 text-sm"
          data-testid="consumo-aviso-app">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>
            Estes números são só do <strong>balcão</strong>. No período escolhido há{' '}
            <strong>{dados.documentos_da_app}</strong> venda(s) da app que não estão aqui
            dentro — a app não regista as personalizações no documento, por isso o consumo
            real é maior do que o que se lê nesta tabela.
          </span>
        </div>
      )}

      {porLigar > 0 && (
        <div className="flex items-start gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground"
          data-testid="consumo-aviso-por-ligar">
          <Link2Off className="h-4 w-4 mt-0.5 shrink-0" />
          <span>
            {porLigar} linha(s) ainda não estão ligadas a um artigo do Estoque. Contam-se
            aqui pelo nome da personalização, mas não têm de onde descontar.
          </span>
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Artigo</TableHead>
                <TableHead className="text-right">Doses</TableHead>
                <TableHead className="text-right">Quantidade</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {linhas.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-center text-muted-foreground py-12 text-sm">
                    {carregando ? 'A somar…' : (
                      'Nada a mostrar neste período. Enquanto as personalizações não '
                      + 'disserem o que gastam (Produtos › Personalizações), esta tabela fica vazia.'
                    )}
                  </TableCell>
                </TableRow>
              ) : linhas.map((linha) => (
                <TableRow key={`${linha.estoque_produto_id || linha.nome}-${linha.unidade}`}
                  data-testid={`consumo-linha-${linha.estoque_produto_id || linha.nome}`}>
                  <TableCell>
                    <span className="font-medium">{linha.nome}</span>
                    {!linha.ligado_ao_estoque && (
                      <span className="ml-2 text-xs text-muted-foreground">(por ligar)</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{linha.doses}</TableCell>
                  <TableCell className="text-right tabular-nums font-medium">
                    {numero(linha.quantidade)} {linha.unidade}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {dados && (
        <p className="text-xs text-muted-foreground" data-testid="consumo-rodape">
          {dados.documentos_do_balcao} venda(s) do balcão no período
          {dados.documentos_da_app > 0 && ` · ${dados.documentos_da_app} da app (fora da conta)`}
          {dados.truncado && ' · a lista foi cortada no limite de documentos do período'}
        </p>
      )}
    </div>
  );
}
