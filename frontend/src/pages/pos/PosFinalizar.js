import React, { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  ArrowLeft, Pencil, X, ChevronDown, Loader2, AlertTriangle, CheckCircle2,
  ShieldAlert, Ban, User, Receipt, Printer, CreditCard, Coins,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import PosCampoValor from './PosCampoValor';
import { contaTravada, duvidaPorApurar, detalhesErroPos, temMaisDe2CasasDecimaisPos } from '@/lib/pos';

// O ecrã de finalizar (Plano 2C, Task 4): três cartões — Total, Cliente e
// Pagamento — depois Mais Opções recolhido, e em baixo o valor recebido, o
// TROCO e EMITIR DOCUMENTO.
//
// É daqui que sai uma Fatura Simplificada REAL à Autoridade Tributária. Uma
// fatura a dobrar não se apaga: corrige-se com uma nota de crédito, e no
// fecho do dia aparece como dinheiro a menos na gaveta que a funcionária tem
// de justificar. Por isso este ficheiro nunca inventa um número, nunca soma
// dinheiro por sua conta, e nunca convida a repetir uma emissão cujo
// resultado não conhece.
//
// Como o PosEntrar, é presentacional em relação ao seu contentor: enche o
// espaço que lhe derem (h-full) e nunca assume que é a página inteira — quem
// decide se isto ocupa o painel da direita ou o ecrã todo é o pai.

const euros = (valor) =>
  `€ ${(Number(valor) || 0).toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// Dinheiro compara-se em CÊNTIMOS INTEIROS, nunca com `===` sobre vírgula
// flutuante: em JS 0.1 + 0.2 dá 0.30000000000000004, e uma soma de pagamentos
// perfeitamente certa ficava para sempre a dizer que faltava um cêntimo — com
// o botão EMITIR bloqueado e ninguém a perceber porquê. É também exactamente o
// que o servidor faz (fiscal.py::finalizar compara `round(sum(...), 2)` com o
// total), por isso o crivo do ecrã e o do servidor dão sempre a mesma resposta.
const centimos = (valor) => Math.round((Number(valor) || 0) * 100);

// Só dígitos e uma única separação decimal — a mesma ideia do PosCampoValor,
// mas para a percentagem, que não leva símbolo de euro nem calculadora.
const aceitarNumero = (texto) => {
  const comPonto = String(texto).replace(',', '.');
  const limpo = comPonto.replace(/[^0-9.]/g, '');
  const partes = limpo.split('.');
  return partes.length > 2 ? partes[0] + '.' + partes.slice(1).join('') : limpo;
};

const soDigitos = (texto) => String(texto || '').replace(/\D/g, '');

const nifPorExtenso = (digitos) =>
  digitos.length === 9 ? `${digitos.slice(0, 3)} ${digitos.slice(3, 6)} ${digitos.slice(6)}` : digitos;

// "Dinheiro", "Dinheiro e Multibanco", "Dinheiro, Multibanco e Glovo" — para as
// razões do bloqueio nomearem SEMPRE o pagamento em causa. Uma razão que diz
// "escreva o valor" sem dizer de quê obriga a operadora a adivinhar qual dos
// três campos está por preencher, que é o mesmo silêncio noutro sítio.
const juntarNomes = (nomes) =>
  nomes.length <= 1
    ? nomes[0] || ''
    : `${nomes.slice(0, -1).join(', ')} e ${nomes[nomes.length - 1]}`;

// Reenche o ÚLTIMO pagamento ainda automático com o que falta para o total.
// É isto que mantém o caso simples num só toque: numa venda de 8,50 €, tocar
// em "Dinheiro" põe lá 8,50 € sem ninguém escrever nada. Um valor escrito à
// mão (auto: false) nunca é tocado — reescrevê-lo por baixo da operadora era
// desfazer-lhe um pagamento misto já acertado, em silêncio.
//
// Fica fora do componente, e recebe o total como argumento, porque também
// corre quando o TOTAL muda (ver o useEffect): dar um desconto à conta depois
// de já ter escolhido "Dinheiro" deixava o pagamento preso no total antigo, e
// a operadora ficava com o EMITIR bloqueado por "pagamentos a mais" sem ter
// mexido em nenhum pagamento.
//
// QUEM nasce automático decide-se no `alternarTipo`, e não aqui: só há um
// automático de cada vez, senão o segundo tipo escolhido nascia como o ÚLTIMO
// automático e ficava ele com o resto — que é ZERO, porque o primeiro já tinha
// o total inteiro. O ecrã dizia "Pagamentos certos" (a soma batia certa!) com o
// EMITIR morto (o servidor recusa `valor: 0` com 422), e não havia uma única
// frase a explicar que faltava escrever um valor.
const reequilibrarAuto = (lista, totalCentimos) => {
  const doFim = [...lista].reverse().findIndex((p) => p.auto);
  if (doFim === -1) return lista;
  const alvo = lista.length - 1 - doFim;
  const outros = lista.reduce((soma, p, i) => (i === alvo ? soma : soma + centimos(p.valor)), 0);
  const resto = Math.max(0, totalCentimos - outros);
  return lista.map((p, i) => (i === alvo ? { ...p, valor: (resto / 100).toFixed(2) } : p));
};

// O cartão dos prints: rótulo pequeno em cima, o valor em baixo, e o lápis à
// direita. O lápis é `h-12 w-12` e não o `size="icon"` de 40px do portal —
// aqui há fila à frente e o alvo tem de ser óbvio ao rato.
function Cartao({ titulo, icone: Icone, aEditar, onEditar, editarLabel, desativado, children }) {
  return (
    <section className="rounded-2xl border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted-foreground flex items-center gap-1.5">
            {Icone && <Icone className="h-4 w-4 shrink-0" />}
            {titulo}
          </p>
          <div className="mt-1">{children}</div>
        </div>
        {onEditar && (
          <Button
            type="button"
            variant={aEditar ? 'secondary' : 'ghost'}
            size="icon"
            className="h-12 w-12 shrink-0"
            onClick={onEditar}
            disabled={desativado}
            aria-label={editarLabel}
            title={editarLabel}
          >
            <Pencil className="h-5 w-5" />
          </Button>
        )}
      </div>
    </section>
  );
}

// --- Total (e o desconto sobre a conta toda) ---------------------------------

function CartaoTotal({ venda, desativado, onAplicarDesconto }) {
  const [aEditar, setAEditar] = useState(false);
  const [pct, setPct] = useState('');
  const [eur, setEur] = useState('');
  const [aGuardar, setAGuardar] = useState(false);

  const totais = venda?.totais || {};
  const temDesconto = (totais.desconto_linhas || 0) > 0 || (totais.desconto_global || 0) > 0;

  const alternar = () => {
    if (aEditar) { setAEditar(false); return; }
    // Reabre sempre com o que está GRAVADO na venda, nunca com o que ficou
    // escrito da vez anterior: o que manda é o servidor, e um campo com um
    // valor "pendurado" fazia a operadora pensar que já tinha aplicado.
    setPct(venda?.desconto_global_pct != null ? String(venda.desconto_global_pct) : '');
    setEur(venda?.desconto_global_eur != null ? String(venda.desconto_global_eur) : '');
    setAEditar(true);
  };

  // O € tem precedência sobre a percentagem — a MESMA regra do servidor
  // (venda.py::_desconto_global_eur: `if eur: ... if pct: ...`) e do desconto
  // por linha. Só viaja o campo que vai contar: mandar os dois deixava a venda
  // com uma percentagem gravada que nunca chega a ser usada, e no reabrir do
  // cartão ela aparecia como se estivesse a fazer alguma coisa.
  const usaEur = eur !== '' && Number(eur) > 0;
  const usaPct = !usaEur && pct !== '' && Number(pct) > 0;

  // A percentagem não leva o crivo das 2 casas decimais e isso é de propósito:
  // o servidor só o aplica ao valor em EUROS (PedidoDescontoGlobal), porque uma
  // percentagem com mais casas acaba na mesma arredondada a cêntimos no
  // `round(base * pct / 100, 2)`. Um crivo mais apertado aqui do que lá era o
  // ecrã a recusar um pedido que o servidor aceitaria.
  const pctInvalida = pct !== '' && (!Number.isFinite(Number(pct)) || Number(pct) < 0 || Number(pct) > 100);
  const eurInvalido = eur !== '' && (!Number.isFinite(Number(eur)) || Number(eur) < 0 || temMaisDe2CasasDecimaisPos(eur));

  const aplicar = async () => {
    if (pctInvalida || eurInvalido || aGuardar) return;
    setAGuardar(true);
    try {
      await onAplicarDesconto({
        desconto_pct: usaPct ? Number(pct) : null,
        desconto_eur: usaEur ? Number(eur) : null,
      });
      setAEditar(false);
    } catch (error) {
      toast.error(detalhesErroPos(error, 'Não foi possível aplicar o desconto.').mensagem);
    } finally {
      setAGuardar(false);
    }
  };

  return (
    <Cartao
      titulo="Total"
      icone={Receipt}
      aEditar={aEditar}
      onEditar={alternar}
      editarLabel="Desconto sobre a conta toda"
      desativado={desativado}
    >
      {/* O total vem SEMPRE do servidor (venda.totais). Este ecrã nunca soma
          preços para os mostrar como total: se somasse, o que a operadora vê e
          o que sai no papel podiam divergir ao cêntimo — o Vendus arredonda
          linha a linha e nós arredondamos na mesma ordem que ele, mas só
          porque é o servidor a fazer essa conta (fiscal.py::_itens_vendus). */}
      <p className="font-heading font-bold text-4xl md:text-5xl tabular-nums">{euros(totais.total)}</p>

      {temDesconto && (
        <div className="mt-2 text-sm text-muted-foreground space-y-0.5">
          <p>Subtotal: {euros(totais.subtotal)}</p>
          {(totais.desconto_linhas || 0) > 0 && <p>Descontos nas linhas: −{euros(totais.desconto_linhas)}</p>}
          {(totais.desconto_global || 0) > 0 && <p>Desconto na conta: −{euros(totais.desconto_global)}</p>}
        </div>
      )}

      {aEditar && (
        <div className="mt-4 rounded-xl bg-muted/60 p-4 space-y-3 animate-fade-in">
          <p className="text-sm font-medium">Desconto a aplicar à conta toda</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="desconto-global-pct">Percentagem</Label>
              <div className="relative">
                <Input
                  id="desconto-global-pct"
                  value={pct}
                  onChange={(e) => setPct(aceitarNumero(e.target.value))}
                  inputMode="decimal"
                  placeholder="0"
                  disabled={aGuardar}
                  className="h-16 pr-10 text-2xl font-heading font-bold text-right"
                />
                <span className="absolute right-4 top-1/2 -translate-y-1/2 text-xl font-heading font-bold text-muted-foreground pointer-events-none">
                  %
                </span>
              </div>
              {pctInvalida && <p className="text-xs text-destructive">A percentagem tem de estar entre 0 e 100.</p>}
            </div>
            <PosCampoValor
              id="desconto-global-eur"
              label="Valor"
              valor={eur}
              onChange={setEur}
              disabled={aGuardar}
            />
          </div>

          {usaEur && pct !== '' && Number(pct) > 0 && (
            <p className="text-xs text-muted-foreground">
              Com os dois preenchidos vale o valor em euros — a percentagem é ignorada.
            </p>
          )}

          <div className="flex gap-2 pt-1">
            <Button type="button" variant="outline" className="h-12 flex-1" onClick={() => setAEditar(false)} disabled={aGuardar}>
              Cancelar
            </Button>
            <Button type="button" className="h-12 flex-1" onClick={aplicar} disabled={pctInvalida || eurInvalido || aGuardar}>
              {aGuardar ? <Loader2 className="h-5 w-5 animate-spin" /> : (usaEur || usaPct ? 'Aplicar' : 'Retirar desconto')}
            </Button>
          </div>
        </div>
      )}
    </Cartao>
  );
}

// --- Cliente -----------------------------------------------------------------

// O cartão NUNCA pode dizer "Consumidor Final" com dígitos escritos por
// terminar: essa frase é uma afirmação sobre a fatura que vai sair, e com um
// NIF a meio a fatura não sai de todo (o `nifValido` do pai bloqueia o EMITIR).
// Era esse o defeito: escrever "5019", mudar de ideias, fechar o cartão pelo
// mesmo lápis — o cartão voltava a "Consumidor Final", estava tudo verde, e o
// EMITIR ficava cinzento sem uma palavra, porque a única mensagem que existia
// ("O NIF tem de ter 9 dígitos") vivia dentro do editor que ela acabara de
// fechar.
//
// Fechar o editor continua a ser sempre possível — prender a operadora dentro
// de um editor com fila à frente é pior do que o que se está a corrigir — mas
// nada se descarta em silêncio: o que ela escreveu fica lá, à vista, e o
// cartão passa a mostrar as duas saídas (terminar, ou assumir Consumidor
// Final) sem ser preciso reabrir o lápis.
function CartaoCliente({ nifTexto, onNifTexto, desativado }) {
  const [aEditar, setAEditar] = useState(false);
  const digitos = soDigitos(nifTexto);
  const incompleto = digitos.length > 0 && digitos.length !== 9;

  return (
    <Cartao
      titulo="Cliente"
      icone={User}
      aEditar={aEditar}
      onEditar={() => setAEditar((v) => !v)}
      editarLabel={incompleto ? 'Terminar o NIF do cliente' : 'Introduzir o NIF do cliente'}
      desativado={desativado}
    >
      {incompleto ? (
        <div className="space-y-1">
          <p className="font-heading font-bold text-2xl text-destructive flex items-center gap-2">
            <AlertTriangle className="h-6 w-6 shrink-0" />
            <span className="tracking-wider break-all">{digitos}</span>
          </p>
          <p className="text-sm text-destructive">
            NIF por terminar — {digitos.length} de 9 dígitos. Assim não é possível emitir.
          </p>
        </div>
      ) : (
        <p className="font-heading font-bold text-2xl">
          {digitos.length === 9 ? nifPorExtenso(digitos) : 'Consumidor Final'}
        </p>
      )}

      {/* As duas saídas à distância de um toque, com o editor FECHADO: quem
          fechou o lápis sem querer não tem de descobrir que o problema se
          resolve lá dentro. */}
      {incompleto && !aEditar && (
        <div className="mt-3 flex flex-col sm:flex-row gap-2">
          <Button type="button" className="h-12 flex-1" onClick={() => setAEditar(true)} disabled={desativado}>
            Terminar o NIF
          </Button>
          <Button type="button" variant="outline" className="h-12 flex-1" onClick={() => onNifTexto('')} disabled={desativado}>
            Consumidor Final
          </Button>
        </div>
      )}

      {aEditar && (
        <div className="mt-4 rounded-xl bg-muted/60 p-4 space-y-3 animate-fade-in">
          <div className="space-y-1.5">
            <Label htmlFor="nif-cliente">Contribuinte (opcional)</Label>
            {/* Aceita espaços na escrita ("123 456 789") e conta só os
                dígitos — é o mesmo que o servidor faz
                (fiscal.py::PedidoFinalizarVenda._valida_nif normaliza para
                dígitos e exige 9). Sem NIF o Vendus assume Consumidor Final,
                por isso o campo vazio é um estado legítimo e não um erro. */}
            <Input
              id="nif-cliente"
              value={nifTexto}
              onChange={(e) => onNifTexto(e.target.value.replace(/[^0-9 ]/g, '').slice(0, 11))}
              inputMode="numeric"
              placeholder="Sem NIF — Consumidor Final"
              disabled={desativado}
              className="h-16 text-2xl font-heading font-bold tracking-wider"
            />
            {incompleto && (
              <p className="text-sm text-destructive">
                O NIF tem de ter 9 dígitos — faltam {9 - digitos.length}.
              </p>
            )}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" className="h-12 flex-1" onClick={() => onNifTexto('')} disabled={desativado || !nifTexto}>
              Consumidor Final
            </Button>
            {/* Com o NIF a meio isto FECHA (e não confirma coisa nenhuma), em
                vez de ficar cinzento: um botão morto aqui era o que empurrava
                a operadora para o lápis, e o lápis era exactamente o caminho
                que apagava a mensagem do ecrã sem apagar o problema. O que ela
                escreveu fica guardado e o cartão fechado di-lo em vermelho. */}
            <Button
              type="button"
              variant={incompleto ? 'secondary' : 'default'}
              className="h-12 flex-1"
              onClick={() => setAEditar(false)}
            >
              {incompleto ? 'Fechar' : 'Confirmar'}
            </Button>
          </div>
        </div>
      )}
    </Cartao>
  );
}

// --- Pagamento ---------------------------------------------------------------

function BotaoTipo({ tipo, escolhido, onEscolher, desativado }) {
  // `pronto: false` = o tipo existe mas nunca foi mapeado a um método do
  // Vendus. Aparece na mesma, morto e com a razão à vista: escondê-lo punha a
  // operadora à procura do botão do Glovo que "desapareceu", e deixá-lo vivo
  // punha-a a descobrir o 422 do servidor já com o cliente à frente
  // (fiscal.py recusa-o com _MSG_TIPO_PAGAMENTO_SEM_VENDUS).
  if (!tipo.pronto) {
    return (
      <div className="rounded-xl border border-dashed bg-muted/40 p-3 text-left cursor-not-allowed">
        <p className="font-medium text-muted-foreground flex items-center gap-1.5">
          <Ban className="h-4 w-4 shrink-0" />
          <span className="truncate">{tipo.nome}</span>
        </p>
        <p className="text-xs text-muted-foreground mt-1 leading-snug">
          Ainda não está ligado ao Vendus — avise o gestor.
        </p>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onEscolher(tipo)}
      disabled={desativado}
      aria-pressed={escolhido}
      className={`h-16 rounded-xl border text-base font-medium px-3 transition-colors active:scale-[0.97] disabled:opacity-50 ${
        escolhido
          ? 'bg-primary text-primary-foreground border-primary'
          : 'bg-card hover:bg-accent'
      }`}
    >
      <span className="block truncate">{tipo.nome}</span>
    </button>
  );
}

// --- Erros da emissão --------------------------------------------------------
//
// Os sabores NÃO se tratam da mesma maneira, e a diferença entre eles é a
// diferença entre repetir de graça e emitir uma segunda Fatura Simplificada
// real à AT:
//
//   'dados'   (422) — a conta ou os pagamentos estão mal. Nada foi ao Vendus.
//                     Corrige-se e emite-se; repetir é seguro.
//   'vendus'  (502) — o Vendus recusou ou está em baixo, mas o servidor SABE
//                     que não saiu documento nenhum. Repetir é seguro.
//   'recusado' (409) — o servidor respondeu e disse o que aconteceu: a conta
//                     foi cancelada a meio, a caixa fechou no outro PC, a
//                     conta MUDOU debaixo da emissão, ou há outra emissão a
//                     decorrer. Cada uma dessas frases já diz por si se saiu
//                     ou não saiu fatura e o que fazer, por isso o painel
//                     mostra-a e não lhe acrescenta nada por cima. Isto caía
//                     no 'incerto', e a moldura dizia o CONTRÁRIO do texto que
//                     estava lá dentro — com o EMITIR desligado, ou seja,
//                     impedindo-a de fazer o que a frase lhe mandava fazer.
//                     **Só chega aqui com a releitura da venda a confirmar
//                     que a conta continua aberta e sem emissão nenhuma por
//                     confirmar** (`PosVenda::contaLimpaNoServidor`) — é essa
//                     prova que dá o direito ao título em letras grandes.
//   'recusado-incerto' — o mesmo 409, mas SEM essa prova: a releitura falhou,
//                     ou trouxe a conta ainda travada. O título de cima
//                     ("Esta emissão não foi feita.") seria uma afirmação
//                     nossa, e para o 409 de uma venda já emitida é
//                     simplesmente falsa — a Fatura Simplificada saiu mesmo.
//                     Medido, com a releitura a falhar: título a dizer que não
//                     foi feita, nenhum número de fatura no ecrã, EMITIR vivo,
//                     e o toque seguinte a pedir mesmo uma segunda emissão.
//                     Aqui diz-se que não se sabe, e não se emite.
//   'nada-saiu'      — o ecrã ficou sem resposta (rede, tecto de espera, um
//                     proxy a cortar), mas a releitura da venda mostrou-a
//                     ainda aberta e SEM emissão por confirmar: é o servidor a
//                     dizer que não saiu fatura nenhuma (ver
//                     `PosVenda::tipoDoErroDeEmissao`). Repetir é seguro.
//   'incerto' (503) — o servidor NÃO SABE se a fatura saiu: a emissão deu
//                     timeout e a verificação por referência externa também
//                     falhou (fiscal.py::VerificacaoFiscalIncerta). Repetir às
//                     cegas pode emitir a MESMA venda duas vezes, e uma Fatura
//                     Simplificada real só se corrige com uma nota de crédito.
//                     Por isso este ecrã não oferece aqui nenhum "tentar
//                     novamente": diz o que se passa e manda chamar o gestor,
//                     que tem a venda na lista de emissões por confirmar do
//                     backoffice (GET /fiscal/reservas-incertas) e o Vendus
//                     aberto ao lado para ver se o documento existe.
function AvisoErro({ erro }) {
  if (!erro) return null;

  if (erro.tipo === 'incerto') {
    return (
      <section className="rounded-2xl border-2 border-destructive bg-destructive/10 p-5 animate-fade-in">
        <div className="flex items-start gap-3">
          <ShieldAlert className="h-7 w-7 text-destructive shrink-0" />
          <div className="space-y-2 min-w-0">
            <p className="font-heading font-bold text-xl">Não sabemos se a fatura saiu.</p>
            <p className="text-sm">
              A ligação ao Vendus falhou a meio da emissão e não foi possível confirmar se o
              documento chegou a ser criado. <strong>Não volte a emitir esta venda.</strong> Se a
              fatura tiver saído, uma segunda tentativa emite outra Fatura Simplificada real à
              Autoridade Tributária, que só se corrige com uma nota de crédito.
            </p>
            <p className="text-sm">
              <strong>Chame o gestor.</strong> A venda ficou registada e esta emissão aparece na
              lista de emissões por confirmar do backoffice — é por lá que se resolve, com o
              documento à vista no Vendus.
            </p>
            <p className="text-sm">
              Não fique presa a este ecrã: volte à conta (a seta em cima) e ponha-a de lado para
              servir o cliente seguinte. O ecrã continua a perguntar ao servidor e mostra o que
              aconteceu a esta venda assim que o gestor a resolver.
            </p>
            {erro.mensagem && <p className="text-xs text-muted-foreground break-words">{erro.mensagem}</p>}
          </div>
        </div>
      </section>
    );
  }

  if (erro.tipo === 'recusado-incerto') {
    return (
      <section className="rounded-2xl border-2 border-destructive bg-destructive/10 p-5 animate-fade-in">
        <div className="flex items-start gap-3">
          <ShieldAlert className="h-7 w-7 text-destructive shrink-0" />
          <div className="space-y-2 min-w-0">
            <p className="font-heading font-bold text-xl">Não sabemos se esta emissão foi feita.</p>
            {/* A frase do servidor, outra vez como mensagem principal: é ela
                que descreve o que aconteceu. O que não se pode é escrever por
                cima dela que não saiu fatura nenhuma — não foi possível
                voltar a ler esta venda para o confirmar. */}
            <p className="text-sm break-words">{erro.mensagem}</p>
            <p className="text-sm">
              O servidor recusou este pedido, mas não foi possível voltar a ler esta venda para
              confirmar se a Fatura Simplificada chegou a sair.{' '}
              <strong>Não volte a emitir esta venda.</strong> Se a fatura tiver saído, uma segunda
              tentativa emite outra Fatura Simplificada real à Autoridade Tributária, que só se
              corrige com uma nota de crédito.
            </p>
            <p className="text-sm">
              Este ecrã está a perguntar ao servidor de poucos em poucos segundos e diz o que
              aconteceu a esta venda assim que houver resposta. <strong>Se ficar assim, chame o
              gestor</strong> — é ele que confirma no Vendus o que saiu desta venda. Entretanto,
              volte à conta (a seta em cima): pode pôr esta conta de lado e servir o cliente
              seguinte.
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (erro.tipo === 'recusado') {
    return (
      <section className="rounded-2xl border-2 border-warning bg-warning/10 p-5 flex items-start gap-3 animate-fade-in">
        <AlertTriangle className="h-7 w-7 text-warning shrink-0" />
        <div className="space-y-2 min-w-0">
          <p className="font-heading font-bold text-xl">Esta emissão não foi feita.</p>
          {/* A frase do SERVIDOR é a mensagem principal, e não uma nota de
              rodapé em letra pequena como nos outros painéis: é ela que diz
              se saiu ou não saiu fatura e o que fazer a seguir, e é diferente
              em cada um dos seis 409 que a rota pode dar. Qualquer coisa que
              este painel escrevesse por cima dela seria uma afirmação nossa
              sobre uma Fatura Simplificada real que só o servidor sabe. */}
          <p className="text-sm break-words">{erro.mensagem}</p>
        </div>
      </section>
    );
  }

  if (erro.tipo === 'nada-saiu') {
    return (
      <section className="rounded-2xl border bg-warning/10 p-4 flex items-start gap-3 animate-fade-in">
        <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="font-medium">Ficámos sem resposta — mas não saiu nenhum documento.</p>
          <p className="text-sm text-muted-foreground mt-1">
            A conta foi confirmada no servidor a seguir à falha: continua aberta e sem nenhuma
            emissão por confirmar. Pode carregar em EMITIR DOCUMENTO outra vez.
          </p>
          {erro.mensagem && <p className="text-xs text-muted-foreground mt-1 break-words">{erro.mensagem}</p>}
        </div>
      </section>
    );
  }

  if (erro.tipo === 'vendus') {
    return (
      <section className="rounded-2xl border bg-warning/10 p-4 flex items-start gap-3 animate-fade-in">
        <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="font-medium">O Vendus não respondeu — não saiu nenhum documento.</p>
          <p className="text-sm text-muted-foreground mt-1">
            Nada foi emitido: pode carregar em EMITIR DOCUMENTO outra vez.
          </p>
          {erro.mensagem && <p className="text-xs text-muted-foreground mt-1 break-words">{erro.mensagem}</p>}
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-destructive/50 bg-destructive/10 p-4 flex items-start gap-3 animate-fade-in">
      <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
      <div className="min-w-0">
        <p className="font-medium">Há algo por corrigir nesta venda.</p>
        <p className="text-sm mt-1 break-words">{erro.mensagem || 'Confirme a conta e os pagamentos.'}</p>
      </div>
    </section>
  );
}

// --- Depois de emitir --------------------------------------------------------

// `troco` é o RETRATO tirado no instante do toque em EMITIR (ver `emitir`), e
// não uma conta refeita aqui: depois de emitir, a venda que chega do servidor
// já é a finalizada, e recalcular o troco a partir dela era arriscar mostrar
// outro número — justamente o número que ela vai tirar da gaveta.
//
// Antes, este ecrã não repetia nem o recebido nem o troco: numa conta de
// 17,35 € paga com 20 €, ela lia "Troco € 2,65", carregava em EMITIR e o 2,65
// desaparecia. Ficava a tirar o troco de memória, com fila à frente — que é
// onde os enganos acontecem, e a diferença só aparece no fecho de caixa.
function DocumentoEmitido({ documento, troco, recuperado, onVoltar }) {
  const emTestes = documento?.modo === 'tests';

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto w-full max-w-lg space-y-4 animate-fade-in">
          {/* O documento não veio da resposta ao toque em EMITIR: veio de uma
              releitura da venda, depois de a emissão ter falhado à frente
              dela (PosVenda::apurarAEmissao). Sem esta frase, a operadora
              acabava de ver um erro e via a seguir o ecrã normal de sucesso,
              sem saber se o que está à frente é desta venda — e a dúvida
              acaba sempre da mesma maneira, a picar tudo outra vez. */}
          {recuperado && (
            <section className="rounded-2xl border-2 border-warning bg-warning/10 p-5 flex items-start gap-3">
              <ShieldAlert className="h-7 w-7 text-warning shrink-0" />
              <div>
                <p className="font-heading font-bold text-lg">Esta fatura já tinha saído.</p>
                <p className="text-sm mt-1">
                  A resposta da emissão perdeu-se pelo caminho e o ecrã foi buscá-la ao servidor. O
                  documento aqui em baixo é o desta conta e é o único que existe —{' '}
                  <strong>não emita outra vez.</strong>
                </p>
              </div>
            </section>
          )}

          {/* O modo 'tests' do Vendus produz um documento que PARECE uma
              fatura e não é nenhuma — não conta para a AT, não conta para o Z.
              Se isto passasse despercebido, uma loja podia faturar um dia
              inteiro para o vazio. */}
          {emTestes && (
            <section className="rounded-2xl border-2 border-warning bg-warning/10 p-5 flex items-start gap-3">
              <ShieldAlert className="h-7 w-7 text-warning shrink-0" />
              <div>
                <p className="font-heading font-bold text-lg">Documento SEM VALOR FISCAL</p>
                <p className="text-sm mt-1">
                  Saiu em modo de testes do Vendus: não foi comunicado à Autoridade Tributária e
                  não serve como fatura. Avise o gestor antes de continuar a vender.
                </p>
              </div>
            </section>
          )}

          {/* Havia dinheiro na conta e o valor recebido não chegou a ser
              escrito, e este documento apareceu por recuperação: o ecrã
              DIZ que não sabe o troco em vez de simplesmente não mostrar o
              cartão. O recebido nunca viaja para o servidor (é uma conta para
              a operadora, não um dado da fatura), por isso não há de onde o ir
              buscar depois — e no caminho normal ela acabou de ver a caixa do
              Troco a dizer "—" e seguiu em frente à mesma; aqui pode nem ter
              chegado a ver ecrã nenhum. */}
          {recuperado && troco?.porEscrever && (
            <section className="rounded-2xl border bg-muted/60 p-4 flex items-start gap-3">
              <Coins className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
              <p className="text-sm min-w-0">
                <span className="font-medium">Não sabemos o troco desta venda.</span> Havia
                pagamento em dinheiro, mas o valor recebido não chegou a ser escrito neste ecrã e
                não fica guardado em lado nenhum. Confirme o dinheiro com o cliente.
              </p>
            </section>
          )}

          {/* Fica ANTES do número e do ATCUD de propósito: o número já está no
              Vendus e não se perde, o troco existe só na cabeça dela e é a
              próxima coisa que as mãos têm de fazer. Em primeiro lugar, nunca
              atrás de um scroll. */}
          {troco?.recebidoCentimos != null && (
            <section className="rounded-2xl border-2 border-primary bg-primary/10 p-5 flex items-start gap-3">
              <Coins className="h-7 w-7 text-primary shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-muted-foreground">
                  Recebido <span className="font-semibold text-foreground tabular-nums">{euros(troco.recebidoCentimos / 100)}</span>
                </p>
                {troco.trocoCentimos >= 0 ? (
                  <>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground mt-2">Troco a entregar</p>
                    <p className="font-heading font-bold text-5xl tabular-nums leading-tight">
                      {euros(troco.trocoCentimos / 100)}
                    </p>
                  </>
                ) : (
                  // O recebido escrito era MENOR do que o devido em dinheiro.
                  // O documento saiu na mesma (o recebido nunca viaja para o
                  // servidor), mas calar isto aqui deixava a gaveta a menos ao
                  // fim do dia sem ninguém saber de onde veio.
                  <p className="text-sm text-destructive mt-2 font-medium">
                    Não houve troco: ficaram por receber {euros(Math.abs(troco.trocoCentimos) / 100)} em dinheiro.
                  </p>
                )}
              </div>
            </section>
          )}

          <section className="rounded-2xl border bg-card p-6 text-center">
            <CheckCircle2 className="h-12 w-12 text-success mx-auto" />
            <p className="text-sm text-muted-foreground mt-3">Documento emitido</p>
            <p className="font-heading font-bold text-3xl mt-1 break-words">{documento?.numero || '—'}</p>

            <div className="mt-5 rounded-xl bg-muted p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">ATCUD</p>
              <p className="font-mono font-bold text-2xl break-all select-all mt-1">{documento?.atcud || '—'}</p>
            </div>

            <p className="mt-5 font-heading font-bold text-4xl tabular-nums">{euros(documento?.total)}</p>
          </section>

          {/* O talão sai sozinho quando o agente de impressão existir (Plano
              3). Enquanto não existir, isto é uma frase e não um botão: um
              botão "Imprimir" que não imprime nada fazia a operadora carregar
              três vezes e dar o cliente por servido sem talão nenhum. */}
          <section className="rounded-2xl border bg-card p-4 text-sm text-muted-foreground flex items-start gap-2">
            <Printer className="h-4 w-4 shrink-0 mt-0.5" />
            <span>
              O talão passa a sair sozinho assim que o agente de impressão da loja existir — ainda
              não existe. Por agora, o documento fica no Vendus e pode ser reimpresso a partir de lá.
            </span>
          </section>

          {documento?.vendus_document_id && (
            <p className="text-center text-xs text-muted-foreground font-mono break-all">
              Ref. Vendus: {documento.vendus_document_id}
            </p>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t bg-card p-4">
        <Button className="w-full h-16 text-lg font-heading font-bold" onClick={onVoltar}>
          Nova Venda
        </Button>
      </div>
    </div>
  );
}

// --- O ecrã ------------------------------------------------------------------

export default function PosFinalizar({
  venda,
  tiposPagamento = [],
  aEmitir = false,
  // A emissão já respondeu (mal) e o ecrã está agora a PERGUNTAR ao servidor
  // o que aconteceu àquela venda. Continua tudo desligado — é a mesma espera
  // para as mãos dela — mas o botão deixa de dizer que está a emitir, porque
  // não está (ver o rótulo, lá em baixo).
  aConfirmar = false,
  onVoltar,
  onAplicarDesconto,
  onEmitir,
  documento = null,
  documentoRecuperado = false,
  erroEmissao = null,
}) {
  // [{ tipo_pagamento_id, valor: string, auto: boolean }] — `valor` é sempre
  // STRING, pelo mesmo motivo do PosCampoValor: um campo controlado que a
  // operadora está a meio de escrever não pode ser arredondado nem "corrigido"
  // debaixo dos dedos dela.
  const [pagamentos, setPagamentos] = useState([]);
  const [recebido, setRecebido] = useState('');
  const [nifTexto, setNifTexto] = useState('');
  // O pagamento que acabou de nascer "por escrever" — só para lhe dar o foco
  // assim que aparece, que é o toque que a operadora ia dar a seguir.
  const [focoPagamentoId, setFocoPagamentoId] = useState(null);
  // Retrato do recebido/troco no instante do EMITIR, para o ecrã do documento
  // emitido o poder repetir (ver DocumentoEmitido).
  const [trocoEntregue, setTrocoEntregue] = useState(null);

  const total = Number(venda?.totais?.total) || 0;
  const totalCentimos = centimos(total);

  const tipos = useMemo(
    () => [...tiposPagamento].sort((a, b) => (a.ordem || 0) - (b.ordem || 0)),
    [tiposPagamento],
  );
  const tipoPorId = useMemo(() => new Map(tipos.map((t) => [t.id, t])), [tipos]);

  // O total mudou (um desconto na conta) — os pagamentos ainda automáticos
  // acompanham-no, os escritos à mão ficam onde estão.
  useEffect(() => {
    setPagamentos((lista) => reequilibrarAuto(lista, totalCentimos));
  }, [totalCentimos]);

  // Um pagamento novo só nasce AUTOMÁTICO quando não há nenhum outro
  // automático para reequilibrar. É isto que faz o caso do balcão ("metade em
  // dinheiro, metade em multibanco") funcionar sozinho:
  //
  //   - primeiro tipo escolhido: não há automático nenhum → nasce automático e
  //     leva o total inteiro. Um toque, venda simples paga.
  //   - segundo tipo com o primeiro ainda automático: nasce VAZIO e com o foco
  //     lá dentro ("escreva o valor"), e o primeiro reequilibra-se sozinho ao
  //     que sobrar. Escrever 5,00 no segundo põe o primeiro no resto, sem mais
  //     nenhum toque.
  //   - tipo novo com todos os outros escritos à mão: volta a haver lugar para
  //     um automático → nasce automático e apanha o que falta.
  //
  // Antes nascia sempre automático e, por ser o ÚLTIMO automático, era ELE que
  // ficava com o resto — zero, porque o anterior tinha o total todo. Nascia a
  // 0,00 €, o servidor recusa 0 (422) e o EMITIR ficava morto com o ecrã a
  // mostrar o visto verde.
  //
  // Sem a forma-de-função do setState de propósito: são duas peças de estado a
  // mudar no mesmo toque, e um updater tem de ser puro (o StrictMode corre-o
  // duas vezes).
  const alternarTipo = (tipo) => {
    const jaEscolhido = pagamentos.some((p) => p.tipo_pagamento_id === tipo.id);
    if (jaEscolhido) {
      setPagamentos(reequilibrarAuto(pagamentos.filter((p) => p.tipo_pagamento_id !== tipo.id), totalCentimos));
      if (focoPagamentoId === tipo.id) setFocoPagamentoId(null);
      return;
    }
    const haAuto = pagamentos.some((p) => p.auto);
    const nova = [...pagamentos, { tipo_pagamento_id: tipo.id, valor: '', auto: !haAuto }];
    setPagamentos(reequilibrarAuto(nova, totalCentimos));
    setFocoPagamentoId(haAuto ? tipo.id : null);
  };

  const escreverValor = (id, valor) => {
    setPagamentos((lista) =>
      reequilibrarAuto(
        lista.map((p) => (p.tipo_pagamento_id === id ? { ...p, valor, auto: false } : p)),
        totalCentimos,
      ),
    );
  };

  const somaCentimos = pagamentos.reduce((soma, p) => soma + centimos(p.valor), 0);
  const faltaCentimos = totalCentimos - somaCentimos;

  const digitosNif = soDigitos(nifTexto);
  const nifValido = digitosNif.length === 0 || digitosNif.length === 9;

  // As DUAS razões para congelar este ecrã — e são duas porque uma delas não
  // sobrevive a nada:
  //
  // · a DÚVIDA POR APURAR é a do erro que acabou de chegar: o servidor disse
  //   que não sabe se a fatura saiu ('incerto'), ou recusou sem que a
  //   releitura da venda conseguisse confirmar o que lhe aconteceu
  //   ('recusado-incerto'). A lista dos dois baldes vive no `lib/pos.js`
  //   porque são dois ecrãs a ter de concordar sobre ela.
  // · `travada` é o travão a sério: vem do SERVIDOR
  //   (`venda.emissao_por_confirmar` — existe reserva fiscal e a venda ainda
  //   não está emitida) e chega a este ecrã em todas as respostas de venda,
  //   por isso sobrevive à seta de voltar, ao F5, à tela de descanso e ao
  //   outro PC. É também exactamente o estado em que o servidor recusa
  //   qualquer escrita nesta conta com 409.
  //
  // As duas continuam a fazer falta: a segunda não acende se a releitura da
  // venda também falhar (rede em baixo), e nesse caso é a primeira que segura
  // o ecrã.
  const duvida = duvidaPorApurar(erroEmissao);
  const travada = contaTravada(venda);
  const congelada = duvida || travada;
  const temLinhas = (venda?.linhas || []).length > 0;

  const nomeDoTipo = (id) => tipoPorId.get(id)?.nome || 'este pagamento';

  // A ÚNICA verdade sobre "porque é que o EMITIR está cinzento". Devolve a
  // razão em português, ou `null` quando não falta nada.
  //
  // Alimenta ao mesmo tempo o botão, o indicador de equilíbrio dos pagamentos
  // e a frase por cima do botão — de propósito, e é esse o remédio: com dois
  // crivos separados, o indicador dizia "Pagamentos certos" a olhar só para a
  // soma enquanto o EMITIR estava morto por outra razão qualquer (um pagamento
  // a 0,00 €, um NIF a meio), e o ecrã não tinha uma única frase a dizer o que
  // faltava fazer. Nada aqui pode bloquear o botão sem produzir uma razão.
  //
  // Os limites são os mesmos do servidor (fiscal.py::PagamentoEntrada: valor
  // > 0 e no máximo 2 casas decimais; PedidoFinalizarVenda: 9 dígitos no NIF;
  // finalizar: a soma tem de bater certo ao cêntimo), para o ecrã nunca deixar
  // passar o que o servidor recusa nem recusar o que ele aceitaria.
  const motivoBloqueio = (() => {
    if (!temLinhas) return { texto: 'A conta não tem nenhum produto — não há nada para faturar.' };
    if (total <= 0) return { texto: 'O total tem de ser positivo para emitir — reveja o desconto aplicado à conta.' };
    if (!nifValido) {
      return {
        texto: `O NIF do cliente está por terminar (${digitosNif.length} de 9 dígitos): termine-o no cartão Cliente, ou toque em Consumidor Final.`,
      };
    }
    if (pagamentos.length === 0) return { texto: 'Escolha como o cliente vai pagar.' };

    // A FORMA dos valores é crivada ANTES de qualquer conta sobre a soma: com
    // "8,505" escrito, o `centimos` arredonda para 851 e a soma passava a
    // acusar um cêntimo a mais — mandava-a corrigir um cêntimo que não existe,
    // quando o que o servidor recusa (PagamentoEntrada) é a terceira casa.
    const comCasasAMais = pagamentos.filter((p) => temMaisDe2CasasDecimaisPos(p.valor));
    if (comCasasAMais.length > 0) {
      const nomes = juntarNomes(comCasasAMais.map((p) => nomeDoTipo(p.tipo_pagamento_id)));
      return { texto: `O valor de ${nomes} não pode ter mais de 2 casas decimais.` };
    }

    // O `pronto` volta a ser confirmado aqui, e não só no botão que não deixa
    // escolhê-lo: se o gestor desmapear um tipo enquanto a venda está a meio, o
    // que já estava escolhido tem de deixar de poder emitir — o servidor
    // recusa-o com 422 e o pior sítio para descobrir isso é o toque no EMITIR,
    // com o cliente à frente. Vem antes do "escreva o valor" porque um tipo
    // desmapeado sai da conta escreva-se lá o que se escrever.
    const semVendus = pagamentos.filter((p) => !tipoPorId.get(p.tipo_pagamento_id)?.pronto);
    if (semVendus.length > 0) {
      const nomes = juntarNomes(semVendus.map((p) => nomeDoTipo(p.tipo_pagamento_id)));
      return { texto: `${nomes} já não está ligado ao Vendus: retire esse pagamento e escolha outro tipo.` };
    }

    // Daqui para baixo é o dinheiro, e só estas razões trazem `curto` +
    // `destaque`: é o que cabe no indicador (rótulo à esquerda, valor grande à
    // direita). O `texto` é a mesma coisa por extenso, para a frase junto ao
    // botão se ler sozinha, sem o indicador à vista.

    // Os pagamentos a somar MAIS do que a conta são avisados ANTES do "escreva
    // o valor", e a ordem é o remédio de um segundo engano do mesmo tipo: numa
    // conta de 8,50 € com Dinheiro automático, escrever 10,00 € em Multibanco
    // faz o automático descer a 0,00 € (o `Math.max(0, ...)` do
    // reequilibrarAuto) — e a única frase que o ecrã tinha era "escreva o valor
    // de Dinheiro", que manda mexer no campo errado. Não há valor nenhum que se
    // possa escrever com o total já ultrapassado: escrever só piora.
    if (faltaCentimos < 0) {
      const aMais = euros(-faltaCentimos / 100);
      return {
        curto: 'Pagamentos a mais',
        destaque: aMais,
        texto: `Os pagamentos somam ${aMais} a mais do que o total da conta — corrija um dos valores.`,
      };
    }

    // `Number('') === 0`, por isso isto apanha tanto o campo em branco como o
    // que ficou mesmo a 0,00 € (dois estados que o servidor recusa na mesma).
    const porEscrever = pagamentos.filter((p) => !(Number(p.valor) > 0));
    if (porEscrever.length > 0) {
      const nomes = juntarNomes(porEscrever.map((p) => nomeDoTipo(p.tipo_pagamento_id)));
      const soUm = porEscrever.length === 1;
      // Se ainda há conta por cobrir, o valor em falta viaja JUNTO com o nome
      // do campo: é a subtracção que ela ia ter de fazer de cabeça (o total
      // menos o que já está distribuído) antes de escrever seja o que for.
      // Quando falta 0 — o caso normal do misto, com o automático a segurar o
      // total inteiro — não se escreve número nenhum, que aí não falta dinheiro
      // nenhum: falta só dizer quanto vai por ali.
      const emFalta = faltaCentimos > 0 ? euros(faltaCentimos / 100) : null;
      return {
        curto: soUm ? `Escreva o valor de ${nomes}` : `Escreva os valores de ${nomes}`,
        destaque: emFalta,
        texto: soUm
          ? `${emFalta ? `Faltam ${emFalta}: escreva` : 'Escreva'} o valor de ${nomes} — ou retire esse pagamento, se o cliente não paga nada por aí.`
          : `${emFalta ? `Faltam ${emFalta}: escreva` : 'Escreva'} os valores de ${nomes} — ou retire os pagamentos que não vai usar.`,
      };
    }

    if (faltaCentimos > 0) {
      const emFalta = euros(faltaCentimos / 100);
      return {
        curto: 'Falta distribuir',
        destaque: emFalta,
        texto: `Falta distribuir ${emFalta} pelos pagamentos escolhidos.`,
      };
    }
    return null;
  })();

  const podeEmitir = !aEmitir && !congelada && !motivoBloqueio;

  // O troco só faz sentido sobre o que é pago EM DINHEIRO: numa venda de 20 €
  // paga com 10 € em Multibanco e 10 € em dinheiro, quem entrega uma nota de
  // 20 € leva 10 € de troco — não 0 €, e muito menos 20 €.
  const devidoEmDinheiroCentimos = pagamentos.reduce(
    (soma, p) => (tipoPorId.get(p.tipo_pagamento_id)?.da_troco ? soma + centimos(p.valor) : soma),
    0,
  );
  const mostrarTroco = pagamentos.some((p) => tipoPorId.get(p.tipo_pagamento_id)?.da_troco);
  const trocoCentimos = centimos(recebido) - devidoEmDinheiroCentimos;

  const unidades = (venda?.linhas || []).reduce((soma, li) => soma + (Number(li.quantidade) || 0), 0);

  const emitir = () => {
    if (!podeEmitir) return;
    // Retrato do recebido e do troco ANTES de a resposta chegar: é o número
    // que ela tem de tirar da gaveta a seguir, e o ecrã do documento emitido
    // substitui este por inteiro. São TRÊS estados, e nenhum deles é uma conta
    // refeita mais tarde (refazê-la sobre a venda já finalizada arriscava
    // mostrar outro número — justamente o que ela vai tirar da gaveta):
    // números, quando houve dinheiro e o recebido foi escrito; `porEscrever`,
    // quando houve dinheiro e o recebido não foi escrito — é este que deixa o
    // ecrã DIZER que não sabe o troco em vez de apenas não o mostrar; e `null`
    // quando não houve dinheiro nenhum, onde não há troco de que falar e um
    // "Troco € 0,00" inventado só punha dúvidas onde não havia.
    //
    // **Fica na memória do ecrã, e não em localStorage. Foi decidido, não
    // esquecido.** Guardá-lo atado ao id da venda só serviria para sobreviver
    // a um F5 — e um F5 leva com ele o próprio id: assim que a venda fica
    // `emitida`, `GET /pos/venda/aberta` devolve `null` e o ecrã fica sem por
    // onde perguntar por ela. Para o retrato guardado valer alguma coisa, o
    // arranque teria de RESSUSCITAR um documento a partir do que estivesse no
    // browser, e é isso que não pode acontecer: a última fatura de ontem à
    // frente do cliente de hoje. Os dois caminhos que mostram um documento (a
    // resposta do EMITIR e a recuperação do `PosVenda::apurarAEmissao`) correm
    // dentro desta mesma montagem do ecrã, que é a que acabou de tirar o
    // retrato — quem acrescentar um terceiro tem de trazer o retrato com ele,
    // ou o ecrã cala-se sobre o troco.
    setTrocoEntregue(
      mostrarTroco
        ? (recebido !== ''
            ? { recebidoCentimos: centimos(recebido), trocoCentimos }
            : { porEscrever: true })
        : null,
    );
    // O VALOR RECEBIDO NUNCA VIAJA PARA O SERVIDOR. O que se manda é sempre o
    // valor DEVIDO de cada pagamento; o recebido e o troco são uma conta para
    // a operadora saber quanto tirar da gaveta. Se o recebido fosse enviado
    // como valor do pagamento, a fatura saía com um total maior do que a venda
    // — e ficava na AT um documento errado, corrigível só com nota de crédito.
    onEmitir({
      pagamentos: pagamentos.map((p) => ({
        tipo_pagamento_id: p.tipo_pagamento_id,
        valor: Number(p.valor),
      })),
      nif: digitosNif || null,
    });
  };

  if (documento) {
    return (
      <DocumentoEmitido
        documento={documento}
        troco={trocoEntregue}
        recuperado={documentoRecuperado}
        onVoltar={onVoltar}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <header className="shrink-0 flex items-center gap-2 border-b bg-card px-3 h-16">
        <Button variant="ghost" size="icon" className="h-12 w-12" onClick={onVoltar} disabled={aEmitir} aria-label="Voltar à conta">
          <ArrowLeft className="h-6 w-6" />
        </Button>
        <h2 className="font-heading font-bold text-xl">Finalizar</h2>
      </header>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto w-full max-w-2xl space-y-4">
          <AvisoErro erro={erroEmissao} />

          <CartaoTotal venda={venda} desativado={aEmitir || congelada} onAplicarDesconto={onAplicarDesconto} />

          {total <= 0 && temLinhas && (
            <p className="text-sm text-destructive px-1">
              O total tem de ser positivo para emitir uma fatura — reveja o desconto aplicado.
            </p>
          )}
          {!temLinhas && (
            <p className="text-sm text-destructive px-1">
              A conta não tem nenhum produto — não há nada para faturar.
            </p>
          )}

          <CartaoCliente nifTexto={nifTexto} onNifTexto={setNifTexto} desativado={aEmitir || congelada} />

          <Cartao titulo="Pagamento" icone={CreditCard}>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 mt-2">
              {tipos.map((t) => (
                <BotaoTipo
                  key={t.id}
                  tipo={t}
                  escolhido={pagamentos.some((p) => p.tipo_pagamento_id === t.id)}
                  onEscolher={alternarTipo}
                  desativado={aEmitir || congelada}
                />
              ))}
              {tipos.length === 0 && (
                <p className="col-span-full text-sm text-muted-foreground">
                  Não há tipos de pagamento activos. Contacte o gestor.
                </p>
              )}
            </div>

            {pagamentos.length > 0 && (
              <div className="mt-4 space-y-3">
                <Separator />
                {pagamentos.map((p) => (
                  <div key={p.tipo_pagamento_id} className="flex items-end gap-2">
                    <div className="flex-1 min-w-0">
                      {/* O `autoFocus` só é honrado na montagem, que é
                          exactamente quando se quer: a linha do pagamento que
                          acabou de nascer vazia recebe o cursor, e o valor
                          escreve-se sem ter de o ir procurar com o rato. */}
                      <PosCampoValor
                        id={`pagamento-${p.tipo_pagamento_id}`}
                        label={tipoPorId.get(p.tipo_pagamento_id)?.nome || 'Pagamento'}
                        valor={p.valor}
                        onChange={(v) => escreverValor(p.tipo_pagamento_id, v)}
                        autoFocus={p.tipo_pagamento_id === focoPagamentoId}
                        disabled={aEmitir || congelada}
                      />
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-16 w-12 shrink-0"
                      onClick={() => alternarTipo(tipoPorId.get(p.tipo_pagamento_id) || { id: p.tipo_pagamento_id })}
                      disabled={aEmitir || congelada}
                      aria-label={`Retirar ${tipoPorId.get(p.tipo_pagamento_id)?.nome || 'pagamento'}`}
                    >
                      <X className="h-5 w-5" />
                    </Button>
                  </div>
                ))}

                {/* O que falta, em tempo real: o servidor recusa com 422 uma
                    soma que não bata EXACTAMENTE com o total
                    (fiscal.py::finalizar), e descobrir isso ao carregar em
                    EMITIR, com o cliente à frente, era o pior sítio possível.
                    O verde vem do MESMO `motivoBloqueio` que decide o botão, e
                    não de uma conta só sobre a soma: o visto verde com o EMITIR
                    cinzento era a pior das mentiras deste ecrã — dizia à
                    operadora que estava tudo certo enquanto o botão não a
                    deixava avançar. Se o que falta não for dos pagamentos (um
                    NIF a meio, por exemplo), aparece aqui à mesma: só há uma
                    verdade e ela tem de estar escrita onde ela está a olhar. */}
                <div
                  className={`rounded-xl px-4 py-3 flex items-center justify-between gap-3 ${
                    motivoBloqueio ? 'bg-warning/10' : 'bg-success/10'
                  }`}
                >
                  <span className="text-sm font-medium flex items-start gap-1.5 min-w-0">
                    {motivoBloqueio ? (
                      <>
                        <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
                        <span className="min-w-0">{motivoBloqueio.curto || motivoBloqueio.texto}</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="h-4 w-4 text-success shrink-0 mt-0.5" /> Pagamentos certos
                      </>
                    )}
                  </span>
                  {motivoBloqueio?.destaque && (
                    <span className="font-heading font-bold text-xl tabular-nums shrink-0">
                      {motivoBloqueio.destaque}
                    </span>
                  )}
                </div>
              </div>
            )}
          </Cartao>

          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button variant="outline" className="w-full h-12 justify-between">
                Mais Opções
                <ChevronDown className="h-4 w-4" />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="rounded-2xl border bg-card p-5 mt-2 text-sm space-y-2">
                <p className="flex justify-between gap-3">
                  <span className="text-muted-foreground">Documento</span>
                  <span className="font-medium text-right">Fatura Simplificada</span>
                </p>
                <p className="flex justify-between gap-3">
                  <span className="text-muted-foreground">Conta</span>
                  <span className="font-medium text-right">
                    {(venda?.linhas || []).length} Produtos / {unidades} Uni.
                  </span>
                </p>
                <Separator />
                <p className="text-muted-foreground leading-snug">
                  Enviar o talão por email e a segunda via ainda não existem neste ecrã. Depois de
                  emitido, o documento fica sempre acessível no Vendus.
                </p>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </div>

      <div className="shrink-0 border-t bg-card p-4">
        <div className="mx-auto w-full max-w-2xl">
          {congelada ? (
            // Nesta situação não há botão nenhum aqui de propósito: qualquer
            // coisa carregável neste sítio, mesmo com outro nome, seria lida
            // como "tentar outra vez" — e é exactamente isso que não se pode
            // fazer sem saber se a fatura saiu. A saída é a seta de voltar, em
            // cima, depois de falar com o gestor.
            //
            // Vale para as duas razões de congelar (ver `congelada`), e é a
            // segunda que fecha o defeito: com o travão preso só ao erro do
            // momento, a seta de voltar limpava-o e dois toques punham o
            // EMITIR aceso outra vez, sobre uma conta totalmente editável.
            <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm">
              <p className="font-semibold">Emissão bloqueada neste posto.</p>
              <p className="text-muted-foreground mt-1">
                Só o gestor pode confirmar se esta fatura saiu. Não repita a emissão.
              </p>
              {/* A saída, escrita onde ela está a olhar. Sem isto, o ecrã
                  dizia-lhe o que NÃO podia fazer e mais nada — e a conta
                  travada prendia o posto inteiro, com o cliente seguinte à
                  espera. A seta de voltar leva à conta, e é lá que estão os
                  dois botões: perguntar outra vez ao servidor, e pôr esta
                  conta de lado para servir o cliente seguinte numa conta
                  nova. */}
              <p className="text-muted-foreground mt-1">
                Volte à conta (a seta em cima, à esquerda): pode pôr esta conta de lado e servir o
                cliente seguinte numa conta nova enquanto o gestor a resolve. Este ecrã continua a
                perguntar ao servidor e destranca-se sozinho assim que houver resposta.
              </p>
            </div>
          ) : (
            <>
              {/* A razão vive AQUI, encostada ao botão que ela está a tentar
                  carregar. Um EMITIR cinzento sem uma frase ao lado é o defeito
                  que se está a corrigir: a operadora ficava a tocar num botão
                  morto sem saber se o problema era a conta, o NIF ou os
                  pagamentos — e a única mensagem que existia podia estar dentro
                  de um cartão fechado, ou não existir de todo. Vem do mesmo
                  `motivoBloqueio` que desliga o botão, por isso não há forma de
                  acrescentar amanhã uma condição nova e voltar ao silêncio. */}
              {motivoBloqueio && (
                <div className="mb-3 flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3">
                  <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
                  <p className="text-sm">
                    <span className="font-semibold">Para emitir: </span>
                    {motivoBloqueio.texto}
                  </p>
                </div>
              )}

              <div className="flex flex-col lg:flex-row lg:items-end gap-3">
              {mostrarTroco && (
                <>
                  <div className="lg:w-64 shrink-0">
                    <PosCampoValor
                      id="valor-recebido"
                      label="Valor recebido"
                      valor={recebido}
                      onChange={setRecebido}
                      disabled={aEmitir}
                    />
                  </div>
                  <div className="lg:w-52 shrink-0 rounded-xl bg-muted px-4 py-2.5">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Troco</p>
                    {recebido === '' ? (
                      <p className="font-heading font-bold text-3xl text-muted-foreground">—</p>
                    ) : trocoCentimos >= 0 ? (
                      <p className="font-heading font-bold text-3xl tabular-nums">{euros(trocoCentimos / 100)}</p>
                    ) : (
                      <p className="text-sm text-destructive leading-tight py-1.5">
                        Faltam {euros(Math.abs(trocoCentimos) / 100)} em dinheiro.
                      </p>
                    )}
                  </div>
                </>
              )}

              <Button
                className="flex-1 h-16 text-lg font-heading font-bold"
                disabled={!podeEmitir}
                onClick={emitir}
              >
                {/* Bloqueado enquanto a emissão está a decorrer. O servidor tem
                    idempotência a sério por trás (fiscal.py: reserva atómica
                    por ext_ref determinística), mas o ecrã não pode CONVIDAR ao
                    duplo toque — a defesa de baixo existe para o caso de tudo o
                    resto falhar, não para ser gasta todos os dias. */}
                {/* E, dentro da espera, DUAS coisas diferentes com nomes
                    diferentes: emitir é o pedido que pode estar 90 s a falar
                    com o Vendus (lib/pos.js::TIMEOUT_COM_VENDUS_MS);
                    confirmar é a pergunta de 15 s que corre A SEGUIR, quando
                    a emissão falhou, para saber o que aconteceu àquela venda.
                    O botão dizia "A emitir…" durante as duas — até 105
                    segundos, e nos últimos 15 não estava a emitir nada. */}
                {aEmitir ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin mr-2" />
                    {aConfirmar ? 'A confirmar no servidor…' : 'A emitir…'}
                  </>
                ) : (
                  'EMITIR DOCUMENTO'
                )}
              </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
