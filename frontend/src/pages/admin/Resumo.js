// O Resumo do gestor: quatro cartões, só leitura, feito para um telemóvel.
//
// Este ficheiro NÃO importa nenhuma função de escrita, e é de propósito: o
// PainelGlobal (o irmão deste, no computador) tem lá dentro sincronizações e o
// «Ligar ao RH», e nada disso pode existir num ecrã que se abre com o polegar
// dentro do autocarro. Todas as decisões estão em lib/resumo.js, corridas por
// lib/resumo.test.js. Aqui só se desenha o que elas decidiram.
import React, {
  useState, useEffect, useCallback, useRef,
} from 'react';
import {
  getFinCompanies, getFinGlobalDashboard, getEstoqueOverview, getAdminDashboard,
} from '../../lib/api';
import { getFatDashboard } from '../../lib/faturacao';
import {
  pede, cartaoVendas, cartaoFinanceiro, cartaoRh, cartaoEstoque, OK,
} from '../../lib/resumo';
import { Card, CardContent } from '../../components/ui/card';
import MonthPicker from '../../components/MonthPicker';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../components/ui/select';
import {
  TrendingUp, CircleDollarSign, Users, Package, ArrowUp, ArrowDown, RefreshCw,
} from 'lucide-react';

const LS_KEY = 'fin_selected_company';
const mesActual = () => new Date().toISOString().slice(0, 7);

function Variacao({ valor }) {
  if (valor == null) return null;
  const sobe = valor >= 0;
  const Seta = sobe ? ArrowUp : ArrowDown;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${sobe ? 'text-emerald-600' : 'text-red-600'}`}>
      <Seta className="h-3 w-3" />
      {Math.abs(valor).toLocaleString('pt-PT', { maximumFractionDigits: 1 })}%
    </span>
  );
}

function Bloco({ titulo, icone: Icone, cartao, destaque = false }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center gap-2 mb-3">
          <Icone className="h-4 w-4 text-muted-foreground shrink-0" />
          <h2 className="text-sm font-medium text-muted-foreground">{titulo}</h2>
        </div>

        {cartao.estado !== OK || cartao.linhas.length === 0 ? (
          // Um cartão OK sem linhas nenhuma (falta tudo) não tem `mensagem`
          // própria — sem isto ficava um <p> vazio, um espaço em branco.
          <p className="text-sm text-muted-foreground">{cartao.mensagem || 'Sem dados'}</p>
        ) : (
          <div className="space-y-3">
            {cartao.linhas.map((l, i) => (
              <div key={`${i}-${l.rotulo}`} className="flex items-baseline justify-between gap-3">
                <span className="text-sm text-muted-foreground truncate">{l.rotulo}</span>
                <span className="flex items-baseline gap-2 shrink-0">
                  <span className={`${destaque ? 'text-2xl' : 'text-base'} font-heading font-bold ${l.alerta ? 'text-red-600' : ''}`}>
                    {l.valor}
                  </span>
                  <Variacao valor={l.variacao} />
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function Resumo() {
  const [empresas, setEmpresas] = useState([]);
  const [empresaId, setEmpresaId] = useState(localStorage.getItem(LS_KEY) || '');
  const [mes, setMes] = useState(mesActual());
  const [cartoes, setCartoes] = useState(null);
  const [aCarregar, setACarregar] = useState(false);
  // Contador do pedido em curso: troca de empresa/mês (ou dois cliques em
  // «Atualizar») pode deixar dois `carregar` a correr ao mesmo tempo. Sem
  // isto, quem escrevia no ecrã era quem respondia por último, não quem foi
  // pedido por último — a empresa lenta chegava depois e sobrepunha os
  // números da empresa nova, com o seletor já a apontar para a certa.
  const pedidoRef = useRef(0);

  useEffect(() => {
    pede(getFinCompanies).then((r) => {
      const lista = r.ok && Array.isArray(r.data) ? r.data : [];
      setEmpresas(lista);
      // A chave gravada é PARTILHADA com o Financeiro (FinExtrato/
      // FinFornecedores lá escrevem o literal 'all' quando o seletor deles
      // está em «todas as empresas»), ou pode ser uma empresa de que já não
      // somos membros. Nos dois casos o <Select> fica sem correspondência
      // enquanto o servidor responde com dados de uma empresa que o ecrã não
      // está a mostrar — substitui pela primeira da lista, ou vazio.
      // Forma funcional para não meter `empresaId` nas dependências.
      setEmpresaId((actual) => (lista.some((e) => e.id === actual) ? actual : (lista[0]?.id || '')));
    });
    // só à entrada: a lista de empresas não muda com o mês
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const carregar = useCallback(async () => {
    const meuPedido = (pedidoRef.current += 1);
    setACarregar(true);
    if (empresaId) localStorage.setItem(LS_KEY, empresaId);
    // Os quatro em paralelo e cada um por sua conta: `pede` não deixa nenhum
    // lançar, por isso um 403 no Financeiro não apaga os outros três.
    //
    // SEM empresa não se chama o Financeiro — e trata-se isso como o 403 que
    // é. Quem não é membro de empresa nenhuma (o Financeiro é por pertença,
    // não por papel: `fin_role_of` não tem atalho para admin) recebia uma
    // lista vazia, e um `return` aqui deixava o ecrã presos em «A carregar…»
    // para sempre. Vendas, RH e Estoque não dependem da empresa escolhida.
    const [fin, fat, est, rh] = await Promise.all([
      empresaId
        ? pede(() => getFinGlobalDashboard({ company_id: empresaId, month: mes }))
        : Promise.resolve({ ok: false, status: 403 }),
      pede(() => getFatDashboard(true)),
      pede(getEstoqueOverview),
      pede(getAdminDashboard),
    ]);
    // Só escreve se ainda formos o pedido mais recente: uma resposta atrasada
    // de um pedido antigo não pode sobrepor o que um pedido mais novo já
    // trouxe (nem apagar o «a carregar» de um pedido novo ainda em voo).
    if (pedidoRef.current !== meuPedido) return;
    setCartoes({
      vendas: cartaoVendas(fat),
      financeiro: cartaoFinanceiro(fin),
      rh: cartaoRh(rh),
      estoque: cartaoEstoque(est),
    });
    setACarregar(false);
  }, [empresaId, mes]);

  useEffect(() => { carregar(); }, [carregar]);

  return (
    <div className="space-y-4 pb-8">
      <div className="flex items-center gap-2">
        <Select value={empresaId} onValueChange={setEmpresaId}>
          <SelectTrigger className="flex-1"><SelectValue placeholder="Empresa" /></SelectTrigger>
          <SelectContent>
            {empresas.map((e) => (
              <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <MonthPicker value={mes} onChange={setMes} />
        <button
          type="button"
          onClick={carregar}
          aria-label="Atualizar"
          className="h-10 w-10 flex items-center justify-center rounded-md border shrink-0"
        >
          <RefreshCw className={`h-4 w-4 ${aCarregar ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {!cartoes ? (
        <p className="text-sm text-muted-foreground px-1">A carregar…</p>
      ) : (
        <div className="space-y-4">
          <Bloco titulo="Vendas" icone={TrendingUp} cartao={cartoes.vendas} destaque />
          <Bloco titulo="Financeiro" icone={CircleDollarSign} cartao={cartoes.financeiro} />
          <Bloco titulo="RH" icone={Users} cartao={cartoes.rh} />
          <Bloco titulo="Estoque" icone={Package} cartao={cartoes.estoque} />
        </div>
      )}
    </div>
  );
}
