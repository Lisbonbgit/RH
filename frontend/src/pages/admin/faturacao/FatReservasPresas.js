import React, { useCallback, useEffect, useState } from 'react';
import {
  getReservasPresas, reconciliarReserva, libertarReserva, getLojas, detalhesErro,
  getContasEsquecidas, arrumarContaEsquecida,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Badge } from '../../../components/ui/badge';
import { Checkbox } from '../../../components/ui/checkbox';
import { Textarea } from '../../../components/ui/textarea';
import { Label } from '../../../components/ui/label';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import {
  ShieldAlert, RefreshCw, Copy, Check, CheckCircle2, AlertTriangle, Clock,
  FileSearch, Unlock, Store, Loader2, Wallet, Ban,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// ---------------------------------------------------------------------------
// O ecrã que as mensagens do módulo já prometiam: "o gestor vê-a (e resolve-a)
// na lista de reservas fiscais presas" (fiscal.py). Uma reserva presa é uma
// venda que reservou o direito a emitir a Fatura Simplificada e nunca gravou o
// documento — o processo morreu entre as duas escritas, ou a verificação ficou
// incerta. Enquanto lá estiver, a conta não junta linha, não desconta, não
// cancela, não finaliza, e a caixa dessa loja NÃO FECHA.
//
// Há duas saídas e elas não são equivalentes, o que manda em todo o desenho
// deste ecrã:
//
//   RECONCILIAR pergunta ao Vendus se a fatura saiu e, se saiu, regista-a. Não
//   emite nada. É a saída segura, e a ÚNICA que traz de volta ao Z e ao
//   dashboard o dinheiro de uma fatura que existe do lado da AT e que o
//   sistema perdeu. Por isso é a primeira, a de maior destaque e a de menos
//   passos.
//
//   LIBERTAR declara ao sistema "confirmei no Vendus que NÃO saiu documento
//   nenhum" e apaga a reserva. Se a fatura tiver saído, isto autoriza uma
//   SEGUNDA Fatura Simplificada da mesma venda entregue à AT, que só se
//   corrige com uma nota de crédito. Por isso o botão é destrutivo, o diálogo
//   escreve o que o gestor tem de ter visto, e o pedido só leva
//   `confirmado_no_vendus=true` quando ele carimba essa declaração à mão.
// ---------------------------------------------------------------------------

// Espelho dos limites do servidor (fiscal.py: `_SEGUNDOS_DE_EMISSAO_NORMAL` e
// `_SEGUNDOS_DE_RETOMA_NORMAL`). Quem manda é sempre o servidor — ele recusa
// com 409 se alguém tentar mexer numa emissão em voo. Estes números servem
// só para o ecrã não CONVIDAR a esse clique e para mostrar quanto falta até a
// janela fechar; nunca para autorizar nada.
const SEGUNDOS_DE_EMISSAO_NORMAL = 300;
const SEGUNDOS_DE_RETOMA_NORMAL = 450;

// Os avisos de "o Z deste turno ficou por acertar" sobrevivem a um F5 de
// propósito: uma venda reconciliada sai desta lista no instante seguinte (fica
// `emitida`), e este aviso passa a ser a única pista, no ecrã, de que aqueles
// euros existiram e não estão nas contas daquele fecho. Num toast que passa,
// perdia-se com o próprio toast.
const CHAVE_AVISOS_Z = 'fat_avisos_z_por_acertar';

const lerAvisosZ = () => {
  try {
    const bruto = window.localStorage.getItem(CHAVE_AVISOS_Z);
    const lista = bruto ? JSON.parse(bruto) : [];
    return Array.isArray(lista) ? lista : [];
  } catch (e) {
    return [];
  }
};

const gravarAvisosZ = (lista) => {
  try {
    window.localStorage.setItem(CHAVE_AVISOS_Z, JSON.stringify(lista));
  } catch (e) {
    // Navegação privada, quota cheia: o aviso continua no ecrã desta sessão.
    // Não se perde nada por não conseguir gravar — só a sobrevivência ao F5.
  }
};

// Euros para o gestor procurar a conta no Vendus. Sem valor legível NÃO se
// inventa um "0,00 €" — mesma regra do servidor (`_total_da_venda` devolve
// None em vez de um número que a gestão possa usar para decidir mal).
const fmtEUR = (valor) => {
  const numero = Number(valor);
  if (valor === null || valor === undefined || !Number.isFinite(numero)) return null;
  return new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(numero);
};

// Mesmo padrão de FatDispositivos — "dd/mm/aaaa às hh:mm".
const formatarData = (isoString) => {
  if (!isoString) return null;
  try {
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return null;
    const data = d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit', year: 'numeric' });
    const hora = d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
    return `${data} às ${hora}`;
  } catch (e) {
    return null;
  }
};

// "há quanto tempo" em português corrido — o gestor precisa de distinguir de
// relance os 40 segundos de uma emissão a decorrer das 14 horas de uma reserva
// de ontem à noite, e "51231.4 s" não faz isso.
const duracaoHumana = (segundos) => {
  if (segundos === null || segundos === undefined || !Number.isFinite(segundos)) return null;
  const s = Math.max(0, Math.round(segundos));
  if (s < 60) return `${s} s`;
  const minutos = Math.floor(s / 60);
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.floor(minutos / 60);
  const restoMinutos = minutos % 60;
  if (horas < 24) return restoMinutos ? `${horas} h ${restoMinutos} min` : `${horas} h`;
  const dias = Math.floor(horas / 24);
  const restoHoras = horas % 24;
  return restoHoras ? `${dias} d ${restoHoras} h` : `${dias} d`;
};

const plural = (n, singular, muitos) => `${n} ${n === 1 ? singular : muitos}`;

const mmss = (segundos) => {
  const s = Math.max(0, Math.round(segundos));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};

// O rótulo curto de cada motivo. A descrição longa vem SEMPRE do servidor
// (`descricao`) — é lá que ela é decidida, com o relógio certo, e duplicá-la
// aqui era garantir que um dia diziam coisas diferentes.
const BADGE_MOTIVO = {
  em_emissao: { texto: 'A emitir agora', classe: 'bg-sky-50 text-sky-700 border-sky-200' },
  em_retoma: { texto: 'Em retoma', classe: 'bg-amber-50 text-amber-700 border-amber-200' },
  incerta: { texto: 'Incerta', classe: 'bg-amber-50 text-amber-700 border-amber-200' },
  orfa: { texto: 'Órfã', classe: 'bg-red-50 text-red-700 border-red-200' },
};

const badgeMotivo = (motivo) =>
  BADGE_MOTIVO[motivo] || { texto: motivo || 'Desconhecido', classe: 'bg-slate-100 text-slate-600 border-slate-200' };

// Um botão de copiar reutilizado pela referência externa (que o gestor tem de
// ir procurar ao Vendus, à mão, e escrever mal uma vez é procurar a venda
// errada) e pelo aviso do Z.
function BotaoCopiar({ valor, rotulo = 'Copiar', testid }) {
  const [copiado, setCopiado] = useState(false);
  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(valor);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch (e) {
      toast.error('Não foi possível copiar. Selecione o texto e copie à mão.');
    }
  };
  return (
    <Button type="button" variant="outline" size="sm" onClick={copiar} data-testid={testid}>
      {copiado ? <Check className="h-3.5 w-3.5 mr-1.5" /> : <Copy className="h-3.5 w-3.5 mr-1.5" />}
      {copiado ? 'Copiado' : rotulo}
    </Button>
  );
}

// Um bloco de texto do servidor. As mensagens deste módulo já vêm escritas em
// português e a dizer o que fazer a seguir — não se resumem, não se traduzem e
// não se substituem por um "ocorreu um erro".
function Bloco({ tom = 'neutro', titulo, children, testid }) {
  const tons = {
    neutro: 'border-border bg-muted/40',
    seguro: 'border-teal-200 bg-teal-50 text-teal-900 dark:bg-teal-950/30 dark:text-teal-100 dark:border-teal-900',
    aviso: 'border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-100 dark:border-amber-900',
    perigo: 'border-red-300 bg-red-50 text-red-900 dark:bg-red-950/30 dark:text-red-100 dark:border-red-900',
  };
  return (
    <div className={`rounded-lg border p-3 text-sm space-y-1.5 ${tons[tom] || tons.neutro}`} data-testid={testid}>
      {titulo && <p className="font-semibold">{titulo}</p>}
      {children}
    </div>
  );
}

export default function FatReservasPresas() {
  const [reservas, setReservas] = useState([]);
  const [lojasPorId, setLojasPorId] = useState({});
  const [loading, setLoading] = useState(true);
  const [erroLista, setErroLista] = useState(null);

  // O relógio: o servidor diz há quantos segundos cada reserva está presa no
  // momento em que respondeu; o ecrã soma-lhe o tempo decorrido DESDE ESSA
  // RESPOSTA. Nunca se compara `criado_em` com o relógio do browser — um PC de
  // escritório com a hora trocada dava uma emissão "presa há -3 horas" e
  // convidava a libertar a reserva de uma fatura a nascer (é o mesmo relógio
  // trocado que já mordeu o servidor uma vez, ver fiscal.py).
  const [carregadoEm, setCarregadoEm] = useState(() => Date.now());
  const [agora, setAgora] = useState(() => Date.now());

  const [alvoReconciliar, setAlvoReconciliar] = useState(null);
  const [notaReconciliar, setNotaReconciliar] = useState('');
  const [aReconciliar, setAReconciliar] = useState(false);

  const [alvoLibertar, setAlvoLibertar] = useState(null);
  const [confirmouNoVendus, setConfirmouNoVendus] = useState(false);
  const [notaLibertar, setNotaLibertar] = useState('');
  const [aLibertar, setALibertar] = useState(false);

  const [resultado, setResultado] = useState(null);
  const [avisosZ, setAvisosZ] = useState(() => lerAvisosZ());
  const [avisoADispensar, setAvisoADispensar] = useState(null);

  // As contas por cobrar de turnos JÁ FECHADOS — ver o comentário do card, lá
  // em baixo. Estado PRÓPRIO, e não misturado com o das reservas: a lista de
  // emergência das reservas presas é a razão de ser deste ecrã e não pode
  // ficar inacessível porque a segunda pergunta falhou — a mesma regra que
  // este ficheiro já aplica às lojas.
  const [esquecidas, setEsquecidas] = useState([]);
  const [erroEsquecidas, setErroEsquecidas] = useState(null);
  const [alvoArrumar, setAlvoArrumar] = useState(null);
  const [confirmouQueNaoFoiPaga, setConfirmouQueNaoFoiPaga] = useState(false);
  const [aArrumar, setAArrumar] = useState(false);

  const carregar = useCallback(async () => {
    setLoading(true);
    setErroLista(null);
    try {
      const { data } = await getReservasPresas();
      setReservas(Array.isArray(data) ? data : []);
      setCarregadoEm(Date.now());
      setAgora(Date.now());
    } catch (error) {
      const { mensagem } = detalhesErro(error, 'Não foi possível carregar as reservas presas.');
      setErroLista(mensagem);
      setReservas([]);
    } finally {
      setLoading(false);
    }
    // As lojas são só para trocar o `loja_id` por um nome, e vão à parte de
    // propósito: uma listagem de emergência não pode ficar inacessível porque
    // a chamada decorativa falhou (mesmo raciocínio do `_total_da_venda` do
    // servidor). Se falhar, mostra-se o id da loja e segue-se.
    try {
      const { data } = await getLojas();
      setLojasPorId(Object.fromEntries((data || []).map((l) => [l.id, l])));
    } catch (error) {
      setLojasPorId({});
    }
    // E as contas por cobrar de turnos fechados, também à parte e pela mesma
    // razão. Se falhar, diz-se que não se sabe — nunca se desenha uma lista
    // vazia, que aqui se leria como "não ficou dinheiro por receber".
    try {
      const { data } = await getContasEsquecidas();
      setEsquecidas(Array.isArray(data) ? data : []);
      setErroEsquecidas(null);
    } catch (error) {
      const { mensagem } = detalhesErro(
        error, 'Não foi possível carregar as contas por cobrar de turnos fechados.');
      setErroEsquecidas(mensagem);
      setEsquecidas([]);
    }
  }, []);

  // --- Arrumar uma conta de um turno fechado ---------------------------------
  //
  // A confirmação à mão é o mesmo desenho do LIBERTAR aqui em cima, e pela
  // mesma família de razões: arrumar declara ao sistema que esta conta NUNCA
  // FOI PAGA, e isso pode ser falso — o cliente pode ter pago em dinheiro e a
  // operadora esquecido-se de finalizar. Nesse caso o dinheiro está na gaveta
  // e a venda nunca existiu: é uma conversa com quem lá estava, não um clique.
  const executarArrumar = async (conta) => {
    setAArrumar(true);
    try {
      await arrumarContaEsquecida(conta.id);
      setAlvoArrumar(null);
      setConfirmouQueNaoFoiPaga(false);
      toast.success('Conta dada por perdida. Fica registada como cancelada, com o seu nome.');
      await carregar();
    } catch (error) {
      // A mensagem é a do servidor, tal e qual — já vem em PT-PT e já diz o
      // que fazer a seguir (ir ao card de cima, ou ao POS). Sem "tente
      // novamente": as três recusas são fundamentadas e repetir dava a mesma.
      mostrarErro(error, 'Não foi possível arrumar esta conta.', null);
      setAlvoArrumar(null);
      setConfirmouQueNaoFoiPaga(false);
      await carregar();
    } finally {
      setAArrumar(false);
    }
  };

  useEffect(() => { carregar(); }, [carregar]);

  // O contador só anda enquanto houver linhas — e é ele que mantém honesto o
  // "volte a ver dentro de MM:SS" de uma emissão a decorrer.
  useEffect(() => {
    if (reservas.length === 0) return undefined;
    const intervalo = setInterval(() => setAgora(Date.now()), 1000);
    return () => clearInterval(intervalo);
  }, [reservas.length]);

  const decorrido = Math.max(0, (agora - carregadoEm) / 1000);

  const presaHa = (r) => (
    r.presa_ha_segundos === null || r.presa_ha_segundos === undefined
      ? null
      : r.presa_ha_segundos + decorrido
  );

  // Estava uma emissão MESMO a decorrer no instante em que esta lista foi
  // carregada? Quem responde é o servidor: `motivo === 'em_emissao'` já é essa
  // resposta, e para a retoma é o relógio DELA (`retoma_reclamada_ha_segundos`,
  // nunca a idade da reserva — uma incerta das 20h retomada à meia-noite tem 4
  // horas de idade e uma retoma de segundos). Uma marca de retoma sem relógio
  // conta como abandonada, não como viva, exactamente como em
  // `fiscal.py::_retoma_em_curso`: tratá-la como viva trancava para sempre a
  // única saída que estas contas têm.
  const emVooAoCarregar = (r) => {
    if (r.em_retoma) {
      const reclamada = r.retoma_reclamada_ha_segundos;
      return reclamada !== null && reclamada !== undefined && reclamada < SEGUNDOS_DE_RETOMA_NORMAL;
    }
    return r.motivo === 'em_emissao';
  };

  // Quanto falta até a janela dessa emissão fechar. Zero significa "já passou"
  // — e mesmo aí os botões NÃO se acendem sozinhos: quem reavalia o estado de
  // uma reserva é o servidor, e para isso é preciso recarregar a lista. Um
  // botão que se acendesse por conta do relógio do browser ficava ao lado de
  // uma descrição do servidor a dizer "não é para mexer".
  const faltaDaJanela = (r) => {
    if (!emVooAoCarregar(r)) return null;
    if (r.em_retoma) {
      const reclamada = r.retoma_reclamada_ha_segundos;
      return Math.max(0, SEGUNDOS_DE_RETOMA_NORMAL - (reclamada + decorrido));
    }
    const presa = presaHa(r);
    if (presa === null) return 0;
    return Math.max(0, SEGUNDOS_DE_EMISSAO_NORMAL - presa);
  };

  const nomeLoja = (r) => (r.loja_id ? (lojasPorId[r.loja_id]?.nome || r.loja_id) : 'Loja desconhecida');

  // Primeiro as que precisam mesmo de alguém (órfãs, incertas, retomas
  // abandonadas), da mais velha para a mais nova — é a mais velha que tem uma
  // caixa por fechar. As emissões a decorrer vão para o fim: são o caso normal
  // de quem abre esta lista a meio do serviço e não são um problema. A ordem
  // fixa-se com o que o SERVIDOR disse ao carregar, e não com o contador a
  // correr, para nenhuma linha saltar de sítio enquanto o gestor a lê.
  const ordenadas = [...reservas].sort((a, b) => {
    const aEmVoo = emVooAoCarregar(a) ? 1 : 0;
    const bEmVoo = emVooAoCarregar(b) ? 1 : 0;
    if (aEmVoo !== bEmVoo) return aEmVoo - bEmVoo;
    // Sem `criado_em` legível são dados estragados de há muito: à cabeça.
    const idadeA = a.presa_ha_segundos === null || a.presa_ha_segundos === undefined ? Infinity : a.presa_ha_segundos;
    const idadeB = b.presa_ha_segundos === null || b.presa_ha_segundos === undefined ? Infinity : b.presa_ha_segundos;
    return idadeB - idadeA;
  });

  const porTratar = ordenadas.filter((r) => !emVooAoCarregar(r)).length;

  // --- Erros -----------------------------------------------------------------
  // A mensagem é a do servidor, tal e qual (já vem em PT-PT e já diz o que
  // fazer a seguir: esperar, usar a outra acção, ou chamar quem trata do
  // sistema). O que este ecrã acrescenta é só o BOTÃO certo — e não acrescenta
  // nenhum "tente novamente" onde tentar outra vez é a coisa errada a fazer.
  const mostrarErro = (error, fallback, repetir) => {
    const { mensagem } = detalhesErro(error, fallback);
    const status = error.response?.status;
    // Só um 502 (o Vendus não respondeu) é que se repete: aí não se concluiu
    // nada — nem que a fatura existe, nem que não existe — e a própria
    // mensagem do servidor manda voltar a tentar. Um 409 é uma recusa
    // fundamentada (a retoma está viva, o documento existe, não há documento
    // nenhum): repetir dava exactamente a mesma recusa.
    setResultado({
      tipo: 'erro',
      titulo: status === 502 ? 'O Vendus não respondeu' : 'A operação não foi feita',
      blocos: [{ tom: status === 502 ? 'aviso' : 'perigo', texto: mensagem }],
      repetir: status === 502 ? repetir : null,
    });
  };

  // --- Reconciliar -----------------------------------------------------------
  const abrirReconciliar = (r) => {
    setAlvoLibertar(null);
    setNotaReconciliar('');
    setAlvoReconciliar(r);
  };

  const executarReconciliar = async (reserva, nota) => {
    setAReconciliar(true);
    try {
      const { data } = await reconciliarReserva(reserva.venda_id, nota);
      setAlvoReconciliar(null);

      const documento = data.documento || {};
      const blocos = [
        { tom: 'seguro', titulo: 'Fatura recuperada', texto: data.o_que_aconteceu },
        {
          tom: 'neutro',
          titulo: 'Documento',
          texto: [
            `Nº ${documento.numero || '—'}`,
            `ATCUD ${documento.atcud || '—'}`,
            fmtEUR(documento.total) || 'total indisponível',
            data.veio_do_vendus_agora
              ? 'Trazido agora do Vendus.'
              : 'Já estava gravado no sistema — o que faltava era ligar-lhe a venda.',
          ].join(' · '),
        },
      ];
      // Um documento em modo de testes não tem valor fiscal nenhum: a AT não o
      // viu. Dizer isto alto evita que a receita apareça no Z como se fosse
      // real (ver VendusModoInvalido em vendus/emissao.py).
      if (documento.modo && documento.modo !== 'normal') {
        blocos.push({
          tom: 'aviso',
          titulo: 'Documento em modo de testes',
          texto: `Este documento foi emitido em modo "${documento.modo}" e NÃO tem valor fiscal — a AT não o recebeu. Chame quem trata do sistema antes de o dar por bom nas contas.`,
        });
      }
      if (data.z_por_acertar && data.aviso_do_z) {
        blocos.push({ tom: 'perigo', titulo: 'Contas do turno por acertar', texto: data.aviso_do_z });
        // E fica na página, não só aqui: ver CHAVE_AVISOS_Z.
        setAvisosZ((antes) => {
          const semRepetido = antes.filter((a) => a.venda_id !== data.venda_id);
          const novos = [
            {
              venda_id: data.venda_id,
              ext_ref: data.ext_ref,
              sessao_id: data.sessao_id,
              numero: documento.numero,
              atcud: documento.atcud,
              total: documento.total,
              loja: nomeLoja(reserva),
              aviso: data.aviso_do_z,
              quando: new Date().toISOString(),
            },
            ...semRepetido,
          ];
          gravarAvisosZ(novos);
          return novos;
        });
      }

      setResultado({
        tipo: 'sucesso',
        titulo: 'Venda reconciliada',
        blocos,
        repetir: null,
      });
      toast.success('Venda reconciliada com a fatura do Vendus');
      carregar();
    } catch (error) {
      // Repetir uma reconciliação é seguro por construção: ela lê, não emite.
      setAlvoReconciliar(null);
      mostrarErro(error, 'Não foi possível reconciliar esta venda.', () => executarReconciliar(reserva, nota));
      carregar();
    } finally {
      setAReconciliar(false);
    }
  };

  // --- Libertar --------------------------------------------------------------
  const abrirLibertar = (r) => {
    setAlvoReconciliar(null);
    setConfirmouNoVendus(false);
    setNotaLibertar('');
    setAlvoLibertar(r);
  };

  const executarLibertar = async () => {
    const reserva = alvoLibertar;
    // Cinto e suspensórios: o botão já está desactivado sem a declaração, mas
    // `confirmado_no_vendus` NUNCA sai daqui a `true` por outra via que não
    // seja o gestor ter carimbado a caixa. Um `true` fixo transformava o 422
    // do servidor — a última rede — em decoração.
    if (!confirmouNoVendus) return;
    setALibertar(true);
    try {
      const { data } = await libertarReserva(reserva.venda_id, true, notaLibertar.trim());
      setAlvoLibertar(null);
      setResultado({
        tipo: 'sucesso',
        titulo: 'Reserva libertada',
        blocos: [
          { tom: 'aviso', titulo: 'O que declarou', texto: data.o_que_confirmou },
          { tom: 'neutro', titulo: 'O que pode acontecer a seguir', texto: data.a_seguir },
        ],
        repetir: null,
      });
      toast.success('Reserva libertada — a conta está destrancada');
      carregar();
    } catch (error) {
      // Libertar NÃO tem botão de "tentar outra vez", em nenhum caso. Se
      // falhou, o mundo pode ter mudado debaixo da declaração que o gestor
      // acabou de assinar (a fatura pode ter saído entretanto) — a saída certa
      // é recarregar a lista e voltar a decidir, não repetir às cegas um
      // pedido que autoriza uma segunda Fatura Simplificada.
      mostrarErro(error, 'Não foi possível libertar esta reserva.', null);
      setAlvoLibertar(null);
      carregar();
    } finally {
      setALibertar(false);
    }
  };

  const dispensarAviso = () => {
    const alvo = avisoADispensar;
    setAvisoADispensar(null);
    setAvisosZ((antes) => {
      const novos = antes.filter((a) => a.venda_id !== alvo.venda_id);
      gravarAvisosZ(novos);
      return novos;
    });
  };

  const alvo = alvoLibertar || alvoReconciliar;
  const alvoTotal = alvo ? fmtEUR(alvo.total_da_venda) : null;

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-reservas-presas-page">
      <PageHeader
        icon={ShieldAlert}
        title="Reservas Fiscais Presas"
        subtitle="O que ficou pendurado: emissões a meio, e contas por cobrar de turnos já fechados"
      >
        <Button variant="outline" onClick={carregar} disabled={loading} data-testid="atualizar-reservas-btn">
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Atualizar
        </Button>
      </PageHeader>

      {/* Avisos de Z por acertar — ficam aqui até alguém dizer que já acertou */}
      {avisosZ.length > 0 && (
        <Card className="border-amber-300 dark:border-amber-900" data-testid="avisos-z-card">
          <CardContent className="p-5 space-y-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" />
              <h3 className="font-semibold">
                Contas de turno por acertar ({avisosZ.length})
              </h3>
            </div>
            <p className="text-sm text-muted-foreground">
              Estas faturas foram recuperadas do Vendus depois de o turno já ter fechado. O relatório Z
              desses turnos foi assinado sem elas e não se reescreve — os valores abaixo têm de ser
              acertados à mão nas contas de cada turno. Este aviso fica aqui até o dispensar.
            </p>
            <div className="space-y-3">
              {avisosZ.map((a) => (
                <div key={a.venda_id} className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-900 p-3 space-y-2" data-testid={`aviso-z-${a.venda_id}`}>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-medium">
                    <span>{a.loja}</span>
                    <span className="text-muted-foreground">·</span>
                    <span>{fmtEUR(a.total) || 'valor indisponível'}</span>
                    <span className="text-muted-foreground">·</span>
                    <span>Fatura nº {a.numero || '—'}</span>
                    <span className="text-muted-foreground text-xs">{formatarData(a.quando)}</span>
                  </div>
                  <p className="text-sm">{a.aviso}</p>
                  <div className="flex flex-wrap gap-2">
                    <BotaoCopiar valor={a.aviso} rotulo="Copiar aviso" testid={`copiar-aviso-z-${a.venda_id}`} />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setAvisoADispensar(a)}
                      data-testid={`dispensar-aviso-z-${a.venda_id}`}
                    >
                      Já acertei este turno
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          {loading && reservas.length === 0 ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : erroLista ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-6" data-testid="reservas-erro">
              <AlertTriangle className="h-12 w-12 text-destructive mb-4" />
              <h3 className="font-medium text-lg">Não foi possível carregar a lista</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-xl">{erroLista}</p>
              <Button className="mt-4" onClick={carregar} data-testid="reservas-erro-repetir">
                <RefreshCw className="h-4 w-4 mr-2" />Tentar outra vez
              </Button>
            </div>
          ) : ordenadas.length === 0 ? (
            // O estado normal é este, e é uma boa notícia: se estivesse vazio e
            // mudo, parecia uma avaria — e é exactamente aqui que o gestor
            // chega com a loja ao telefone a dizer que a caixa não fecha.
            <div className="flex flex-col items-center justify-center py-12 text-center px-6" data-testid="reservas-vazio">
              <CheckCircle2 className="h-12 w-12 text-teal-600 mb-4" />
              <h3 className="font-medium text-lg">Nenhuma reserva fiscal presa</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-xl">
                É assim que deve estar: todas as vendas fecharam a emissão da Fatura Simplificada e
                nenhuma conta está trancada. Esta lista só ganha linhas quando uma emissão fica a meio
                — por exemplo se o servidor reiniciar entre reservar o número e gravar o documento.
              </p>
            </div>
          ) : (
            <div className="p-4 space-y-4">
              <p className="text-sm text-muted-foreground px-1" data-testid="reservas-resumo">
                {porTratar === 0
                  ? `${plural(ordenadas.length, 'emissão a decorrer', 'emissões a decorrer')} neste momento. Nenhuma precisa de si — volte a ver dentro de minutos.`
                  : `${plural(porTratar, 'conta trancada', 'contas trancadas')} à espera de si${
                      ordenadas.length > porTratar
                        ? `, e ${plural(ordenadas.length - porTratar, 'emissão a decorrer', 'emissões a decorrer')}`
                        : ''
                    }.`}
              </p>

              {ordenadas.map((r) => {
                const emVoo = emVooAoCarregar(r);
                const falta = faltaDaJanela(r);
                const badge = badgeMotivo(r.motivo);
                const total = fmtEUR(r.total_da_venda);
                const caixaAberta = r.sessao_estado === 'aberta';
                return (
                  <div
                    key={r.venda_id}
                    className={`rounded-xl border p-4 space-y-3 ${emVoo ? 'bg-muted/30' : 'bg-card'}`}
                    data-testid={`reserva-presa-${r.venda_id}`}
                  >
                    {/* Cabeçalho: loja, valor, há quanto tempo, porquê */}
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0">
                        <span className="flex items-center gap-1.5 font-semibold">
                          <Store className="h-4 w-4 text-muted-foreground shrink-0" />
                          {nomeLoja(r)}
                        </span>
                        <span className="text-lg font-bold" data-testid={`reserva-total-${r.venda_id}`}>
                          {total || <span className="text-base font-medium text-muted-foreground">valor indisponível</span>}
                        </span>
                        <Badge variant="outline" className={badge.classe} data-testid={`reserva-motivo-${r.venda_id}`}>
                          {badge.texto}
                        </Badge>
                        <Badge
                          variant="outline"
                          className={caixaAberta
                            ? 'bg-teal-50 text-teal-700 border-teal-200'
                            : 'bg-slate-100 text-slate-600 border-slate-200'}
                          data-testid={`reserva-caixa-${r.venda_id}`}
                        >
                          {r.sessao_estado ? (caixaAberta ? 'Caixa aberta' : 'Caixa fechada') : 'Caixa desconhecida'}
                        </Badge>
                      </div>
                      <span className="flex items-center gap-1.5 text-sm text-muted-foreground shrink-0" data-testid={`reserva-idade-${r.venda_id}`}>
                        <Clock className="h-3.5 w-3.5" />
                        {duracaoHumana(presaHa(r))
                          ? `presa há ${duracaoHumana(presaHa(r))}`
                          : 'há quanto tempo, não se sabe'}
                      </span>
                    </div>

                    {/* Porquê está presa — texto do servidor */}
                    <p className="text-sm">{r.descricao}</p>

                    {/* A referência que o gestor tem de procurar no Vendus */}
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs uppercase tracking-wide text-muted-foreground">Referência no Vendus</span>
                      <code className="rounded bg-muted px-2 py-1 text-xs font-mono select-all" data-testid={`reserva-extref-${r.venda_id}`}>
                        {r.ext_ref || '— (reserva sem referência)'}
                      </code>
                      {r.ext_ref && <BotaoCopiar valor={r.ext_ref} testid={`copiar-extref-${r.venda_id}`} />}
                    </div>

                    <p className="text-xs text-muted-foreground">
                      Conta {r.venda_id}{r.estado_da_venda ? ` · venda ${r.estado_da_venda}` : ''}
                      {r.sessao_id ? ` · turno ${r.sessao_id}` : ''}
                      {formatarData(r.criado_em) ? ` · reservada a ${formatarData(r.criado_em)}` : ''}
                    </p>

                    {/* As saídas possíveis, que dependem da caixa — texto do servidor */}
                    <Bloco tom={caixaAberta ? 'neutro' : 'aviso'} testid={`reserva-saidas-${r.venda_id}`}>
                      <p>{r.saidas}</p>
                    </Bloco>

                    {emVoo ? (
                      <Bloco tom="neutro" titulo="Não é para mexer" testid={`reserva-em-voo-${r.venda_id}`}>
                        {falta > 0 ? (
                          <p>
                            Uma emissão desta venda pode estar a falar com o Vendus neste instante.
                            Volte a ver dentro de <span className="font-mono font-semibold">{mmss(falta)}</span>.
                          </p>
                        ) : (
                          <p>
                            A janela dessa emissão já passou. Carregue em <span className="font-medium">Atualizar</span> para
                            o servidor reavaliar esta reserva — só ele pode dizer o que ela é agora.
                          </p>
                        )}
                      </Bloco>
                    ) : (
                      <div className="flex flex-wrap gap-2 pt-1">
                        {/* A segura primeiro, e é a única cheia: é a que traz o
                            dinheiro de volta e nunca entrega nada à AT. */}
                        <Button onClick={() => abrirReconciliar(r)} data-testid={`reconciliar-${r.venda_id}`}>
                          <FileSearch className="h-4 w-4 mr-2" />
                          Reconciliar com o Vendus
                        </Button>
                        <Button
                          variant="outline"
                          className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                          onClick={() => abrirLibertar(r)}
                          data-testid={`libertar-${r.venda_id}`}
                        >
                          <Unlock className="h-4 w-4 mr-2" />
                          Libertar reserva
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* --- Contas por cobrar de turnos JÁ FECHADOS --------------------------
          **O buraco que este card fecha, com os números que se mediram.**
          14,10 € divididos por duas pessoas, ninguém cobrado, caixa fechada,
          turno seguinte aberto. `GET /pos/venda/repartidas` → `[]`; `GET
          /pos/venda/aberta` → `null`; `GET /pos/caixa/contas-abertas` →
          `{quantas: 0}`. As duas partes continuavam na base a `estado=aberta`
          com o `sessao_id` do turno anterior, e NENHUM ecrã voltava a
          mostrá-las. O `contas_abertas` que o fecho grava na sessão não tinha
          um único leitor em todo o repositório: escrevia-se para o Z de papel
          e mais nada.

          **Porque é que vive AQUI, e não num ecrã próprio.** É o mesmo género
          de problema das reservas presas — ficou a meio, não se resolve
          sozinho, e é preciso alguém ir perguntar o que aconteceu — e este é
          o ecrã a que o gestor já vem quando a loja lhe telefona. Um ecrã novo
          era um segundo sítio a que ele teria de se lembrar de ir; e as duas
          listas cruzam-se (uma conta com reserva fiscal aparece nas duas, e a
          de cima é que manda), o que se lê muito melhor lado a lado do que em
          páginas diferentes.

          **E porque é que não vive no POS.** A operadora do turno seguinte não
          tem nada que mexer numa conta de um turno que outra pessoa fechou —
          mexer nela mudava um Z já assinado, e o servidor recusa-lho desde
          esta ronda (`venda.py::_garante_sessao_desta_venda_aberta`). Um ecrã
          do balcão a mostrá-las era pedir-lhe uma coisa que ela não pode
          fazer. */}
      <Card data-testid="contas-esquecidas-card">
        <CardContent className="p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Wallet className="h-5 w-5 text-muted-foreground shrink-0" />
            <h3 className="font-semibold">
              Contas por cobrar de turnos fechados
              {esquecidas.length > 0 ? ` (${esquecidas.length})` : ''}
            </h3>
          </div>

          {erroEsquecidas ? (
            <Bloco tom="aviso" titulo="Não foi possível carregar esta lista" testid="esquecidas-erro">
              <p>{erroEsquecidas}</p>
            </Bloco>
          ) : esquecidas.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="esquecidas-vazio">
              Nenhuma. Todos os turnos fechados deixaram as contas deles
              resolvidas — cobradas ou canceladas. Esta lista ganha linhas
              quando uma conta fica aberta e o turno fecha por cima dela: uma
              parte de uma conta repartida que ninguém pagou, ou uma conta
              travada que ficou à espera do gestor e nunca foi resolvida. O relatório Z desse
              turno regista-as, mas o Z é papel — é aqui que elas continuam a
              existir.
            </p>
          ) : (
            <>
              {/* O texto diz as DUAS famílias desde que existe a marca
                  `entregue_ao_gestor_em`: as contas de turnos já fechados (as
                  de sempre) e as que a operadora ENTREGOU ao gestor, que podem
                  ser do turno que está a decorrer neste instante. O que as une
                  é o que esta lista existe para dizer — nenhum ecrã do POS lhes
                  chega. Dizer só "num turno que já fechou" era descrever
                  metade da lista, e era a metade que o gestor nunca tinha
                  visto. */}
              <p className="text-sm text-muted-foreground" data-testid="esquecidas-resumo">
                {plural(esquecidas.length, 'conta ficou', 'contas ficaram')} aberta
                {esquecidas.length === 1 ? '' : 's'} sem ninguém no POS que lhes chegue —{' '}
                <span className="font-semibold text-foreground">
                  {fmtEUR(esquecidas.reduce((t, c) => t + (Number(c.total) || 0), 0))}
                </span>
                . Esse dinheiro não foi facturado nem entrou em nenhum Z como venda.
                São as contas de turnos que já fecharam (com a caixa fechada, o balcão
                só vê o turno que está a decorrer) e as que a operadora entregou ao
                gestor por estarem travadas — essas saíram do balcão de propósito e
                não voltam lá, mesmo que o turno delas ainda esteja aberto.
              </p>

              <div className="space-y-3">
                {esquecidas.map((c) => (
                  <div
                    key={c.id}
                    className="rounded-xl border bg-card p-4 space-y-3"
                    data-testid={`conta-esquecida-${c.id}`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0">
                        <span className="flex items-center gap-1.5 font-semibold">
                          <Store className="h-4 w-4 text-muted-foreground shrink-0" />
                          {nomeLoja(c)}
                        </span>
                        <span className="text-lg font-bold" data-testid={`esquecida-total-${c.id}`}>
                          {fmtEUR(c.total) || (
                            <span className="text-base font-medium text-muted-foreground">
                              valor indisponível
                            </span>
                          )}
                        </span>
                        {/* "Faltou cobrar uma pessoa" e "ficou uma conta a
                            meio" são duas conversas diferentes com quem lá
                            estava. */}
                        {/* Tokens, e não uma cor fixa: estes dois crachás
                            nasceram nesta ronda e não têm de herdar a paleta
                            escrita à mão dos de cima (que são anteriores aos
                            tokens do tema). */}
                        {c.conta_mae_id && (
                          <Badge variant="outline" className="bg-muted text-muted-foreground border-border">
                            Parte de uma conta repartida
                          </Badge>
                        )}
                        {c.reserva_fiscal_por_resolver && (
                          <Badge variant="outline" className="bg-destructive/10 text-destructive border-destructive/30" data-testid={`esquecida-travada-${c.id}`}>
                            Reserva fiscal por resolver
                          </Badge>
                        )}
                        {/* A que chegou aqui pela porta NOVA. Sem este crachá,
                            o gestor via uma conta do turno de HOJE no meio das
                            esquecidas de ontem e não percebia porquê. */}
                        {c.entregue_ao_gestor_em && (
                          <Badge variant="outline" className="bg-primary/10 text-primary border-primary/30" data-testid={`esquecida-entregue-${c.id}`}>
                            Entregue ao gestor no POS
                            {c.entregue_ao_gestor_por?.nome ? ` por ${c.entregue_ao_gestor_por.nome}` : ''}
                          </Badge>
                        )}
                      </div>
                      <span className="flex items-center gap-1.5 text-sm text-muted-foreground shrink-0">
                        <Clock className="h-3.5 w-3.5" />
                        {formatarData(c.criada_em) || 'data desconhecida'}
                      </span>
                    </div>

                    <p className="text-xs text-muted-foreground">
                      Conta {c.id}
                      {c.caixa_nome ? ` · caixa ${c.caixa_nome}` : ''}
                      {c.sessao_id ? ` · turno ${c.sessao_id}` : ''}
                      {/* O turno SEM estado é uma sessão que desapareceu da
                          base — dinheiro sem turno nenhum, que é ainda mais
                          invisível do que o resto. Diz-se. */}
                      {c.sessao_estado
                        ? (formatarData(c.sessao_fechada_em)
                          ? ` · fechado a ${formatarData(c.sessao_fechada_em)}` : '')
                        : ' · o turno desta conta já não existe na base de dados'}
                      {c.sessao_fechada_por?.nome ? ` por ${c.sessao_fechada_por.nome}` : ''}
                    </p>

                    {c.reserva_fiscal_por_resolver ? (
                      <Bloco tom="perigo" titulo="Esta resolve-se primeiro em cima">
                        <p>
                          Tem uma reserva fiscal por resolver: pode existir uma Fatura Simplificada
                          real desta venda do lado da Autoridade Tributária. Enquanto não se souber,
                          esta conta não se arruma daqui — resolva a reserva na lista acima
                          (reconciliar, ou libertar depois de confirmar no Vendus) e volte aqui.
                        </p>
                      </Bloco>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2">
                        <BotaoCopiar valor={c.id} rotulo="Copiar referência" testid={`copiar-esquecida-${c.id}`} />
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => { setConfirmouQueNaoFoiPaga(false); setAlvoArrumar(c); }}
                          data-testid={`arrumar-esquecida-${c.id}`}
                        >
                          <Ban className="h-4 w-4 mr-2" />
                          Dar por perdida
                        </Button>
                        <span className="text-xs text-muted-foreground">
                          Só depois de perguntar a quem estava nesse turno.
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Reconciliar — a acção segura */}
      <Dialog open={!!alvoReconciliar} onOpenChange={(o) => !o && !aReconciliar && setAlvoReconciliar(null)}>
        <DialogContent data-testid="reconciliar-dialog" className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Reconciliar com o Vendus</DialogTitle>
            <DialogDescription>
              {alvoReconciliar ? `${nomeLoja(alvoReconciliar)} · ${alvoTotal || 'valor indisponível'}` : ''}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <Bloco tom="seguro" titulo="Esta acção é segura">
              <p>
                Pergunta ao Vendus se a Fatura Simplificada desta venda chegou a sair. Se saiu, grava-a
                no sistema e a venda passa a emitida. <span className="font-medium">Não emite nada</span> —
                não entrega nada de novo à AT, só regista o que já existe do lado dela.
              </p>
              <p>
                É também a única forma de esta receita voltar ao relatório Z e ao dashboard quando a
                caixa do turno já fechou.
              </p>
            </Bloco>

            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">Referência</span>
              <code className="rounded bg-muted px-2 py-1 text-xs font-mono select-all">{alvoReconciliar?.ext_ref}</code>
            </div>

            <div className="space-y-2">
              <Label htmlFor="nota-reconciliar">Nota (opcional)</Label>
              <Textarea
                id="nota-reconciliar"
                value={notaReconciliar}
                onChange={(e) => setNotaReconciliar(e.target.value)}
                placeholder="O que viu, quem avisou — fica no registo do sistema."
                maxLength={300}
                data-testid="nota-reconciliar-input"
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAlvoReconciliar(null)} disabled={aReconciliar}>
              Cancelar
            </Button>
            <Button
              type="button"
              onClick={() => executarReconciliar(alvoReconciliar, notaReconciliar.trim())}
              disabled={aReconciliar}
              data-testid="confirmar-reconciliar-btn"
            >
              {aReconciliar ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FileSearch className="h-4 w-4 mr-2" />}
              {aReconciliar ? 'A perguntar ao Vendus...' : 'Perguntar ao Vendus'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Libertar — a acção perigosa: só depois de uma declaração a sério */}
      <Dialog open={!!alvoLibertar} onOpenChange={(o) => !o && !aLibertar && setAlvoLibertar(null)}>
        <DialogContent data-testid="libertar-dialog" className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle className="text-destructive">Libertar a reserva desta venda</DialogTitle>
            <DialogDescription>
              {alvoLibertar ? `${nomeLoja(alvoLibertar)} · ${alvoTotal || 'valor indisponível'}` : ''}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <Bloco tom="perigo" titulo="O que isto autoriza">
              <p>
                Libertar a reserva destranca a conta — e com ela destranca também uma nova emissão
                desta venda. Se a Fatura Simplificada JÁ saiu no Vendus, a próxima finalização entrega
                à AT uma <span className="font-semibold">segunda fatura do mesmo açaí</span>, que só se
                corrige com uma nota de crédito.
              </p>
            </Bloco>

            <div className="space-y-2">
              <p className="text-sm font-semibold">Antes de continuar, no Vendus:</p>
              <ol className="text-sm space-y-2 list-decimal list-inside">
                <li>Abra o Vendus.</li>
                <li className="space-y-1">
                  <span>Procure esta referência externa:</span>
                  <span className="flex flex-wrap items-center gap-2 mt-1">
                    <code className="rounded bg-muted px-2 py-1 text-xs font-mono select-all" data-testid="libertar-extref">
                      {alvoLibertar?.ext_ref}
                    </code>
                    {alvoLibertar?.ext_ref && (
                      <BotaoCopiar valor={alvoLibertar.ext_ref} testid="copiar-extref-libertar" />
                    )}
                  </span>
                </li>
                <li>
                  Confirme que <span className="font-semibold">não existe lá nenhum documento</span> desta
                  venda ({alvoTotal || 'valor indisponível'}
                  {formatarData(alvoLibertar?.criado_em) ? `, de ${formatarData(alvoLibertar?.criado_em)}` : ''}).
                </li>
              </ol>
            </div>

            <Bloco tom="neutro" titulo="Não tem a certeza?">
              <p>
                Comece por <span className="font-medium">Reconciliar</span>: pergunta ao Vendus por si e
                não emite nada. Se lá existir fatura, ela é gravada e esta conta resolve-se sozinha;
                se não existir, o Vendus di-lo e volta aqui com a resposta.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-1"
                onClick={() => abrirReconciliar(alvoLibertar)}
                data-testid="ir-para-reconciliar-btn"
              >
                <FileSearch className="h-3.5 w-3.5 mr-1.5" />
                Reconciliar em vez disto
              </Button>
            </Bloco>

            {/* A declaração. É ela — e só ela — que põe
                `confirmado_no_vendus=true` no pedido. O rótulo fica AO LADO da
                caixa (htmlFor), nunca à volta dela: uma etiqueta que embrulha
                um controlo do Radix chega a apanhar dois cliques e a deixar a
                caixa por marcar depois de o gestor a ter marcado. */}
            <div className="flex items-start gap-3 rounded-lg border border-destructive/40 p-3">
              <Checkbox
                id="confirmou-no-vendus"
                checked={confirmouNoVendus}
                onCheckedChange={(v) => setConfirmouNoVendus(v === true)}
                className="mt-0.5 border-destructive data-[state=checked]:bg-destructive"
                data-testid="confirmou-no-vendus-checkbox"
              />
              <Label htmlFor="confirmou-no-vendus" className="text-sm font-normal leading-relaxed cursor-pointer">
                Declaro que abri o Vendus, procurei a referência{' '}
                <span className="font-mono font-medium">{alvoLibertar?.ext_ref}</span> e vi que
                {' '}<span className="font-semibold">NÃO existe lá nenhum documento desta venda</span>.
              </Label>
            </div>

            <div className="space-y-2">
              <Label htmlFor="nota-libertar">Nota (opcional)</Label>
              <Textarea
                id="nota-libertar"
                value={notaLibertar}
                onChange={(e) => setNotaLibertar(e.target.value)}
                placeholder="O que viu no Vendus — fica no registo, com o seu nome."
                maxLength={300}
                data-testid="nota-libertar-input"
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAlvoLibertar(null)} disabled={aLibertar}>
              Cancelar
            </Button>
            <Button
              type="button"
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={executarLibertar}
              disabled={aLibertar || !confirmouNoVendus}
              data-testid="confirmar-libertar-btn"
            >
              {aLibertar ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Unlock className="h-4 w-4 mr-2" />}
              {aLibertar ? 'A libertar...' : 'Libertar reserva'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* O desfecho — em diálogo, nunca só num toast: estas mensagens dizem o
          que ficou por fazer e o gestor tem de as poder ler com tempo. */}
      <Dialog open={!!resultado} onOpenChange={(o) => !o && !aReconciliar && setResultado(null)}>
        <DialogContent data-testid="resultado-dialog" className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className={resultado?.tipo === 'erro' ? 'text-destructive' : ''}>
              {resultado?.titulo}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {(resultado?.blocos || []).map((b, i) => (
              <Bloco key={i} tom={b.tom} titulo={b.titulo} testid={`resultado-bloco-${i}`}>
                <p>{b.texto}</p>
              </Bloco>
            ))}
          </div>
          <DialogFooter>
            {/* O "tentar outra vez" só existe quando repetir é mesmo a coisa
                certa a fazer (um 502 do Vendus, ver `mostrarErro`) — e o
                diálogo fica aberto durante a tentativa, para o botão poder
                mostrar que está a acontecer alguma coisa. */}
            {resultado?.repetir && (
              <Button
                type="button"
                variant="outline"
                onClick={() => resultado.repetir()}
                disabled={aReconciliar}
                data-testid="resultado-repetir-btn"
              >
                {aReconciliar
                  ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  : <RefreshCw className="h-4 w-4 mr-2" />}
                {aReconciliar ? 'A perguntar ao Vendus...' : 'Tentar outra vez'}
              </Button>
            )}
            <Button type="button" onClick={() => setResultado(null)} disabled={aReconciliar} data-testid="resultado-fechar-btn">
              Fechar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dar por perdida — a acção que declara "isto nunca foi pago". Diálogo
          próprio e com uma declaração à mão, e não um `AlertDialog` de sim/não,
          pela mesma razão do LIBERTAR: se a conta TIVER sido paga em dinheiro e
          a operadora se tiver esquecido de finalizar, cancelá-la apaga do
          sistema a única pista de que aqueles euros entraram na gaveta. O
          caminho fácil não pode ser o destrutivo. */}
      <Dialog
        open={!!alvoArrumar}
        onOpenChange={(o) => { if (!o && !aArrumar) { setAlvoArrumar(null); setConfirmouQueNaoFoiPaga(false); } }}
      >
        <DialogContent data-testid="arrumar-dialog" className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle className="text-destructive">Dar esta conta por perdida</DialogTitle>
            <DialogDescription>
              {alvoArrumar
                ? `${nomeLoja(alvoArrumar)} · ${fmtEUR(alvoArrumar.total) || 'valor indisponível'}`
                : ''}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <Bloco tom="perigo" titulo="O que isto declara">
              <p>
                Que esta conta NUNCA foi paga. Ela passa a cancelada, com o seu nome e a data, e
                sai desta lista. O relatório Z daquele turno não muda — continua a registá-la como
                tendo ficado por cobrar, que é a verdade do turno.
              </p>
            </Bloco>
            <Bloco tom="aviso" titulo="Antes de carregar">
              <p>
                Pergunte a quem estava nesse turno. Se o cliente pagou em dinheiro e a operadora se
                esqueceu de finalizar, o dinheiro está na gaveta e a venda nunca existiu no sistema —
                dar a conta por perdida apaga a última pista de que aqueles euros entraram, e a
                diferença do Z fica sem explicação.
              </p>
            </Bloco>

            <div className="flex items-start gap-3 rounded-lg border p-3">
              <Checkbox
                id="confirmar-nao-foi-paga"
                checked={confirmouQueNaoFoiPaga}
                onCheckedChange={(v) => setConfirmouQueNaoFoiPaga(v === true)}
                data-testid="confirmar-nao-foi-paga"
              />
              <Label htmlFor="confirmar-nao-foi-paga" className="text-sm font-normal leading-snug">
                Confirmo que perguntei a quem estava nesse turno e que esta conta não foi paga.
              </Label>
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => { setAlvoArrumar(null); setConfirmouQueNaoFoiPaga(false); }}
              disabled={aArrumar}
            >
              Cancelar
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => executarArrumar(alvoArrumar)}
              disabled={aArrumar || !confirmouQueNaoFoiPaga}
              data-testid="confirmar-arrumar-btn"
            >
              {aArrumar ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Ban className="h-4 w-4 mr-2" />}
              {aArrumar ? 'A arrumar...' : 'Dar por perdida'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dispensar um aviso de Z apaga a única pista que resta desses euros —
          por isso pergunta-se. */}
      <AlertDialog open={!!avisoADispensar} onOpenChange={(o) => !o && setAvisoADispensar(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Já acertou as contas deste turno?</AlertDialogTitle>
            <AlertDialogDescription>
              Este aviso desaparece do ecrã e não volta. Só o dispense depois de os{' '}
              {fmtEUR(avisoADispensar?.total) || 'euros desta fatura'} estarem acertados nas contas do
              turno {avisoADispensar?.sessao_id}.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Ainda não</AlertDialogCancel>
            <AlertDialogAction onClick={dispensarAviso} data-testid="confirmar-dispensar-aviso-btn">
              Já acertei
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
