// A lista das paragens de uma secção da rota (plano F3 T3.36), no painel do planeador (CrmRota, T3.38/T3.39):
// a secção "Rota" (arrastável) e as "⚠️ Fechadas neste dia" e "⚠️ Não cabem no horário". Só desenha a `vista`
// do planeador (`lib/crm/planeador.js`: `vista.seccoes.<secção>`, linhas `{id, numero, nome, fase, motivo,
// rotuloMotivo, tempo, chegada, espera, textoAviso, google, waze, podeSubir, podeDescer, seccao}`) e avisa a
// página do que a pessoa fez; quem grava é o planeador (cada ação grava logo, §1 "Gravação").
//
// Reordenar (§1 "Arrastar", sem bibliotecas; as regras estão em `lib/crm/reordenar.js`, com testes):
//  - a pega (`button.crm-pega`, 44 × 44 px e `touch-action: none`) arrasta-se com o rato ou o dedo (Pointer
//    Events com `setPointerCapture`): o arrasto só começa depois de 4 px (`deveIniciarArrasto`), a linha segue
//    o ponteiro (`translateY`) e as outras abrem lugar (`desvioDaLinha`); o destino é o `indiceDestino` com as
//    linhas medidas no início do arrasto; perto das pontas do contentor que desloca (o painel, ou o planeador
//    no telemóvel), a lista desloca-se sozinha (`deslocamentoAutomatico`). Ao largar noutro sítio,
//    `aoMover(de, para)`, com as posições desta lista;
//  - com o teclado na pega (`teclaNaLista`): Espaço ou Enter pegam e largam, as setas movem, o Escape e o Tab
//    cancelam, e a perda do foco também (`cancelarMovimento`). Os anúncios vão para uma região
//    `aria-live="assertive"` (um anúncio igual ao anterior leva um espaço a mais, para se voltar a ouvir).
//    Durante o movimento o DOM não se reordena (mover o nó com o foco tirava-lho): a posição mostra-se com
//    `translateY`; ao largar, o foco volta à pega da paragem movida;
//  - se a lista mudar (outra resposta do servidor) com uma paragem pegada ou a arrastar, o movimento cai.
//  O jsdom do Jest não tem `setPointerCapture`: chama-se com `?.` (correção "Receita F3e" do plano).
//
// O detalhe de cada paragem (Radix `Collapsible`): o motivo, o tempo na loja, "Subir"/"Descer", "Manter" (as
// fechadas), "Pôr na rota" (as que não cabem), "Retirar" e os links do Google Maps e do Waze. Os links só
// passam pelo `hrefNavegacao` (regra 9 do §0) e abrem noutro separador com `rel="noopener noreferrer"`
// (correção "T3.36 / T3.38 / receita F3e"); com "Evitar portagens" ligado, junto do Waze, o
// `TEXTO_WAZE_PORTAGENS` (correção "T3.10"). Em leitura só não há pega nem botões: só o que se vê e os links.
// Com `desligada` (sem rede, conflito), os controlos aparecem desligados.
//
// Os nomes das lojas entram como texto (o React escapa-os).
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronDown, ExternalLink, GripVertical, Trash2 } from 'lucide-react';
import { Button } from '../ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../ui/collapsible';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { hrefNavegacao } from '../../lib/crm/dom';
import { ORDEM } from '../../lib/crm/fases';
import {
  INSTRUCOES_ARRASTAR,
  cancelarMovimento,
  desvioDaLinha,
  deslocamentoAutomatico,
  deveIniciarArrasto,
  indiceDestino,
  teclaNaLista,
} from '../../lib/crm/reordenar';
import { MOTIVOS, ROTULOS_MOTIVO, TEXTO_WAZE_PORTAGENS } from '../../lib/crm/rota';
import './crm.css';

export const TEXTO_SUBIR = 'Subir';
export const TEXTO_DESCER = 'Descer';
export const TEXTO_RETIRAR = 'Retirar';
export const TEXTO_MANTER = 'Manter';
export const TEXTO_POR_NA_ROTA = 'Pôr na rota';
export const TEXTO_MOTIVO = 'Motivo';
export const TEXTO_TEMPO = 'Tempo na loja (min)';
export const TEXTO_GOOGLE_MAPS = 'Google Maps';
export const TEXTO_WAZE = 'Waze';
export const ROTULO_PEGA = 'pega para arrastar';

// Os tempos de serviço que o servidor aceita (o validador da rota: inteiro de 1 a 240).
const TEMPO_MINIMO = 1;
const TEMPO_MAXIMO = 240;

const nomeDaLinha = (linha) => (typeof linha.nome === 'string' && linha.nome.trim() !== '' ? linha.nome : '');

// "Entrega · 10 min" e "Chegada 10:35 (espera 5 min)", só com o que existe.
function textoDoMotivo(linha) {
  const partes = [];
  if (linha.rotuloMotivo) partes.push(linha.rotuloMotivo);
  if (Number.isInteger(linha.tempo)) partes.push(`${linha.tempo} min`);
  return partes.join(' · ');
}

function textoDaChegada(linha) {
  if (!linha.chegada) return null;
  return linha.espera ? `Chegada ${linha.chegada} (espera ${linha.espera} min)` : `Chegada ${linha.chegada}`;
}

// O contentor que desloca a lista: o primeiro antepassado com deslocamento vertical (o painel no computador, o
// planeador no telemóvel), ou a página.
function contentorQueDesloca(no) {
  const vista = no?.ownerDocument?.defaultView;
  for (let atual = no?.parentElement; atual && vista; atual = atual.parentElement) {
    const { overflowY } = vista.getComputedStyle(atual);
    if (/^(?:auto|scroll|overlay)$/.test(overflowY) && atual.scrollHeight > atual.clientHeight) return atual;
  }
  return no?.ownerDocument?.scrollingElement ?? no?.ownerDocument?.documentElement ?? null;
}

// A caixa visível do contentor (a página: a janela inteira).
function caixaDoContentor(contentor) {
  const documento = contentor.ownerDocument;
  if (contentor === documento.scrollingElement || contentor === documento.documentElement) {
    return { top: 0, bottom: documento.defaultView.innerHeight };
  }
  const { top, bottom } = contentor.getBoundingClientRect();
  return { top, bottom };
}

// A captura do ponteiro (o jsdom não a tem; o browser recusa um ponteiro que já não existe): nunca rebenta.
function capturar(alvo, id) {
  try {
    alvo.setPointerCapture?.(id);
  } catch {
    // Sem captura, o arrasto continua enquanto o ponteiro estiver sobre a pega.
  }
}

function soltar(alvo, id) {
  try {
    if (alvo.hasPointerCapture?.(id)) alvo.releasePointerCapture?.(id);
  } catch {
    // O browser já a soltou (o pointerup solta-a sozinho).
  }
}

// Pára o deslocamento automático de um arrasto.
function pararQuadro(p) {
  if (p?.quadro) p.vista.cancelAnimationFrame?.(p.quadro);
  if (p) p.quadro = null;
}

// O desvio, em px, de cada linha enquanto uma paragem se move de `de` para `para` (as caixas medidas no início):
// a que se move vai para o lugar da de destino; as do meio abrem lugar com a altura dela (mais o intervalo).
function desvios(caixas, de, para, dyDaMovida) {
  const altura = caixas[de].bottom - caixas[de].top;
  const intervalo = caixas.length > 1 ? Math.max(0, caixas[1].top - caixas[0].bottom) : 0;
  return caixas.map((_, i) => {
    if (i === de) return dyDaMovida;
    return desvioDaLinha(i, de, para) * (altura + intervalo);
  });
}

// O desvio da paragem pegada pelo teclado: até ao sítio da linha de destino.
function desvioDoTeclado(caixas, de, para) {
  if (para > de) return caixas[para].bottom - caixas[de].bottom;
  if (para < de) return caixas[para].top - caixas[de].top;
  return 0;
}

function NumeroDaParagem({ linha }) {
  const fase = ORDEM.includes(linha.fase) ? `pino--${linha.fase}` : '';
  if (!Number.isInteger(linha.numero)) {
    return <span aria-hidden="true" className={`crm-amostra-fase mx-1.5 mt-1 ${fase}`} />;
  }
  return (
    <span
      aria-hidden="true"
      className={`${fase} inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-[3px] border-[color:var(--cor-pino,#cfcfcf)] bg-white text-xs font-extrabold text-[#221a2e]`}
    >
      {linha.numero}
    </span>
  );
}

// O tempo na loja: escreve-se à vontade e grava ao sair do campo ou com Enter, só se mudou (e nunca o mesmo
// texto duas vezes seguidas: o 422 já disse porquê).
function CampoTempo({ id, linha, desligada, aoMudarTempo }) {
  const tempoAtual = linha.tempo === null || linha.tempo === undefined ? '' : String(linha.tempo);
  const [rascunho, setRascunho] = useState(tempoAtual);
  const enviado = useRef(null);

  useEffect(() => {
    setRascunho(tempoAtual);
    enviado.current = null;
  }, [tempoAtual]);

  function confirmar() {
    // O campo numérico do browser já não deixa espaços nem letras: vai o texto tal e qual (o planeador apara-o).
    if (rascunho === tempoAtual || rascunho === enviado.current) return;
    enviado.current = rascunho;
    aoMudarTempo?.(linha.id, rascunho);
  }

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{TEXTO_TEMPO}</Label>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={TEMPO_MINIMO}
        max={TEMPO_MAXIMO}
        step={1}
        className="h-11"
        value={rascunho}
        disabled={desligada}
        onChange={(evento) => setRascunho(evento.target.value)}
        onBlur={confirmar}
        onKeyDown={(evento) => {
          if (evento.key === 'Enter') {
            evento.preventDefault();
            confirmar();
          }
        }}
      />
    </div>
  );
}

function Detalhe({ idBase, linha, somenteLeitura, desligada, arrastavel, evitarPortagens, acoes }) {
  const google = hrefNavegacao(linha.google);
  const waze = hrefNavegacao(linha.waze);
  const idMotivo = `${idBase}-motivo`;
  const conhecido = MOTIVOS.includes(linha.motivo);

  return (
    <div className="grid gap-3 border-t px-3 pb-3 pt-3">
      {somenteLeitura ? (
        <p className="text-sm text-muted-foreground">{textoDoMotivo(linha)}</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor={idMotivo}>{TEXTO_MOTIVO}</Label>
            <Select
              value={conhecido ? linha.motivo : ''}
              disabled={desligada}
              onValueChange={(motivo) => {
                if (motivo !== linha.motivo) acoes.aoMudarMotivo?.(linha.id, motivo);
              }}
            >
              <SelectTrigger id={idMotivo} className="h-11">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MOTIVOS.map((motivo) => (
                  <SelectItem key={motivo} value={motivo} className="min-h-11">
                    {ROTULOS_MOTIVO[motivo]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <CampoTempo id={`${idBase}-tempo`} linha={linha} desligada={desligada} aoMudarTempo={acoes.aoMudarTempo} />
        </div>
      )}

      {!somenteLeitura && (
        <div className="flex flex-wrap gap-2">
          {arrastavel && (
            <>
              <Button
                type="button"
                variant="outline"
                className="h-11"
                disabled={desligada || !linha.podeSubir}
                onClick={() => acoes.aoSubir?.(linha.id)}
              >
                <ArrowUp className="h-4 w-4" aria-hidden="true" />
                {TEXTO_SUBIR}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-11"
                disabled={desligada || !linha.podeDescer}
                onClick={() => acoes.aoDescer?.(linha.id)}
              >
                <ArrowDown className="h-4 w-4" aria-hidden="true" />
                {TEXTO_DESCER}
              </Button>
            </>
          )}
          {linha.seccao === 'fechada' && acoes.aoManter && (
            <Button type="button" variant="outline" className="h-11" disabled={desligada} onClick={() => acoes.aoManter(linha.id)}>
              {TEXTO_MANTER}
            </Button>
          )}
          {linha.seccao === 'nao_cabe' && acoes.aoPorNaRota && (
            <Button type="button" variant="outline" className="h-11" disabled={desligada} onClick={() => acoes.aoPorNaRota(linha.id)}>
              {TEXTO_POR_NA_ROTA}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            className="h-11 text-destructive hover:text-destructive"
            disabled={desligada}
            onClick={() => acoes.aoRetirar?.(linha.id)}
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            {TEXTO_RETIRAR}
          </Button>
        </div>
      )}

      {(google || waze) && (
        <div className="grid gap-1.5">
          <div className="flex flex-wrap gap-2">
            {google && (
              <Button asChild variant="secondary" className="h-11">
                <a href={hrefNavegacao(google)} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-4 w-4" aria-hidden="true" />
                  {TEXTO_GOOGLE_MAPS}
                </a>
              </Button>
            )}
            {waze && (
              <Button asChild variant="secondary" className="h-11">
                <a href={hrefNavegacao(waze)} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-4 w-4" aria-hidden="true" />
                  {TEXTO_WAZE}
                </a>
              </Button>
            )}
          </div>
          {waze && evitarPortagens && <p className="text-sm text-muted-foreground">{TEXTO_WAZE_PORTAGENS}</p>}
        </div>
      )}
    </div>
  );
}

// linhas: as linhas de uma secção (`vista.seccoes.<secção>`); vazia não desenha nada.
// titulo: o nome da secção ("Rota", "⚠️ Fechadas neste dia"…), opcional.
// arrastavel: a secção "Rota" (com a pega, "Subir" e "Descer"); somenteLeitura: sem pega nem botões;
// desligada: os controlos aparecem desligados (sem rede, conflito); evitarPortagens: o aviso do Waze.
// aoMover(de, para), aoSubir(id), aoDescer(id), aoRetirar(id), aoMudarMotivo(id, motivo),
// aoMudarTempo(id, texto), aoManter(id), aoPorNaRota(id): as ações do planeador.
export default function ListaParagens({
  linhas,
  titulo,
  arrastavel = false,
  somenteLeitura = false,
  desligada = false,
  evitarPortagens = false,
  aoMover,
  aoSubir,
  aoDescer,
  aoRetirar,
  aoMudarMotivo,
  aoMudarTempo,
  aoManter,
  aoPorNaRota,
}) {
  const idBase = useId();
  const idTitulo = `${idBase}-titulo`;
  const idInstrucoes = `${idBase}-instrucoes`;
  const lista = Array.isArray(linhas) ? linhas : [];
  const ids = lista.map((linha) => linha.id).join('\n');
  const comPega = arrastavel && !somenteLeitura;
  const podeArrastar = comPega && !desligada && lista.length > 1;

  const listaRef = useRef(null);
  const linhasRef = useRef(new Map());
  const pegasRef = useRef(new Map());
  // O arrasto com o ponteiro em curso (fora do estado: muda a cada movimento).
  const ponteiro = useRef(null);
  const focarDepois = useRef(null);

  // O movimento pelo teclado e o arrasto, cada um com os ids da lista em que começou.
  const [teclado, setTeclado] = useState(null);
  const [arrasto, setArrasto] = useState(null);
  const [anuncio, setAnuncio] = useState('');

  // Só contam na lista em que começaram, e enquanto se puder arrastar (a rede a cair desliga a pega).
  const pegada = podeArrastar && teclado && teclado.ids === ids ? teclado : null;
  const aArrastar = podeArrastar && arrasto && arrasto.ids === ids ? arrasto : null;

  function anunciar(texto) {
    setAnuncio((anterior) => (anterior === texto ? `${texto}\u00a0` : texto));
  }

  function medir() {
    return lista.map((linha) => {
      const no = linhasRef.current.get(linha.id);
      const caixa = no ? no.getBoundingClientRect() : null;
      return caixa ? { top: caixa.top, bottom: caixa.bottom } : { top: NaN, bottom: NaN };
    });
  }

  // --- O ponteiro ---

  function atualizarArrasto() {
    const p = ponteiro.current;
    if (!p || !p.iniciado) return;
    const deslocado = (p.contentor?.scrollTop ?? 0) - p.deslocamento0;
    const dy = p.y - p.y0 + deslocado;
    const caixa = p.caixas[p.de];
    p.para = indiceDestino((caixa.top + caixa.bottom) / 2 + dy, p.caixas, p.de);
    setArrasto({ ids: p.ids, de: p.de, para: p.para, dy, caixas: p.caixas });
  }

  // Perto das pontas do contentor, desloca-o um passo por quadro enquanto o arrasto dura.
  function deslocarSozinho() {
    const p = ponteiro.current;
    if (!p || !p.iniciado || !p.contentor) return;
    const passo = deslocamentoAutomatico(p.y, caixaDoContentor(p.contentor));
    if (passo !== 0) {
      p.contentor.scrollTop += passo;
      atualizarArrasto();
    }
    p.quadro = p.vista.requestAnimationFrame?.(deslocarSozinho) ?? null;
  }

  function largarPonteiro(evento, { mover }) {
    const p = ponteiro.current;
    if (!p || evento.pointerId !== p.id) return;
    pararQuadro(p);
    ponteiro.current = null;
    soltar(evento.currentTarget, evento.pointerId);
    setArrasto(null);
    if (mover && p.iniciado && p.ids === ids && p.para !== p.de) aoMover?.(p.de, p.para);
  }

  function aoPremir(evento, indice) {
    if (!podeArrastar || pegada || ponteiro.current) return;
    if (evento.pointerType === 'mouse' && evento.button !== 0) return;
    const contentor = contentorQueDesloca(listaRef.current);
    ponteiro.current = {
      id: evento.pointerId,
      ids,
      de: indice,
      para: indice,
      x0: evento.clientX,
      y0: evento.clientY,
      y: evento.clientY,
      iniciado: false,
      caixas: medir(),
      contentor,
      deslocamento0: contentor?.scrollTop ?? 0,
      vista: evento.currentTarget.ownerDocument.defaultView,
      quadro: null,
    };
    capturar(evento.currentTarget, evento.pointerId);
  }

  function aoMoverPonteiro(evento) {
    const p = ponteiro.current;
    if (!p || evento.pointerId !== p.id) return;
    if (p.ids !== ids) {
      largarPonteiro(evento, { mover: false });
      return;
    }
    p.y = evento.clientY;
    if (!p.iniciado) {
      if (!deveIniciarArrasto(evento.clientX - p.x0, evento.clientY - p.y0)) return;
      p.iniciado = true;
      p.quadro = p.vista.requestAnimationFrame?.(deslocarSozinho) ?? null;
    }
    evento.preventDefault();
    atualizarArrasto();
  }

  // Se a lista mudar a meio do arrasto, o arrasto cai (o `aArrastar` já não conta; aqui larga-se o ponteiro).
  useEffect(() => {
    const p = ponteiro.current;
    if (p && p.ids !== ids) {
      pararQuadro(p);
      ponteiro.current = null;
    }
  }, [ids]);

  // Ao desmontar, nada fica a deslocar.
  useEffect(() => {
    const arrastoAtual = ponteiro;
    return () => {
      pararQuadro(arrastoAtual.current);
      arrastoAtual.current = null;
    };
  }, []);

  // --- O teclado ---

  function aoTecla(evento, indice, linha) {
    if (!podeArrastar || ponteiro.current?.iniciado) return;
    const r = teclaNaLista(pegada?.estado ?? null, {
      tecla: evento.key,
      indice,
      total: lista.length,
      nome: nomeDaLinha(linha),
      repetida: evento.repeat,
    });
    if (r.tratada) evento.preventDefault();
    if (r.estado === null) setTeclado(null);
    else if (r.estado !== pegada?.estado) {
      setTeclado({ ids, estado: r.estado, caixas: pegada?.caixas ?? medir() });
    }
    if (r.anuncio) anunciar(r.anuncio);
    if (r.acao) {
      focarDepois.current = lista[r.acao.de]?.id ?? null;
      aoMover?.(r.acao.de, r.acao.para);
    }
  }

  function aoSairDaPega() {
    // Ao largar, a página reordena as linhas e o nó da pega pode mudar de sítio (e perder o foco por instantes):
    // isso não é sair da pega.
    if (focarDepois.current !== null) return;
    const r = cancelarMovimento(pegada?.estado ?? null);
    setTeclado(null);
    if (r.anuncio) anunciar(r.anuncio);
  }

  // Depois de largar com o teclado, o foco volta à pega da paragem movida (que pode ter mudado de sítio no DOM).
  useLayoutEffect(() => {
    const id = focarDepois.current;
    if (id === null) return;
    focarDepois.current = null;
    const pega = pegasRef.current.get(id);
    if (pega && pega.ownerDocument.activeElement !== pega) pega.focus();
  });

  if (lista.length === 0) return null;

  // Os desvios de cada linha (px), a arrastar ou com uma paragem pegada; senão nenhum.
  let deslocamentos = null;
  let movida = null;
  if (aArrastar) {
    deslocamentos = desvios(aArrastar.caixas, aArrastar.de, aArrastar.para, aArrastar.dy);
    movida = aArrastar.de;
  } else if (pegada) {
    // Na mesma lista (os mesmos ids), o `para` do teclaNaLista já está dentro dela.
    const { de, para } = pegada.estado;
    deslocamentos = desvios(pegada.caixas, de, para, desvioDoTeclado(pegada.caixas, de, para));
    movida = de;
  }
  const acoes = { aoSubir, aoDescer, aoRetirar, aoMudarMotivo, aoMudarTempo, aoManter, aoPorNaRota };

  return (
    <section aria-labelledby={titulo ? idTitulo : undefined} className="grid gap-2">
      {titulo && (
        <h3 id={idTitulo} className="font-heading text-base font-bold">
          {titulo}
        </h3>
      )}
      {comPega && (
        <>
          <p id={idInstrucoes} className="sr-only">
            {INSTRUCOES_ARRASTAR}
          </p>
          <div aria-live="assertive" aria-atomic="true" className="sr-only" data-testid="crm-anuncio-paragens">
            {anuncio}
          </div>
        </>
      )}
      <ol ref={listaRef} className="crm-lista-paragens">
        {lista.map((linha, indice) => {
          const desvio = deslocamentos ? deslocamentos[indice] : 0;
          const estilo = desvio && Number.isFinite(desvio) ? { transform: `translateY(${desvio}px)` } : undefined;
          return (
            <LinhaParagem
              key={linha.id}
              idBase={`${idBase}-${indice}`}
              linha={linha}
              estilo={estilo}
              movida={movida === indice}
              somenteLeitura={somenteLeitura}
              desligada={desligada}
              arrastavel={arrastavel}
              comPega={comPega}
              podeArrastar={podeArrastar}
              idInstrucoes={idInstrucoes}
              evitarPortagens={evitarPortagens}
              acoes={acoes}
              refLinha={(no) => {
                if (no) linhasRef.current.set(linha.id, no);
                else linhasRef.current.delete(linha.id);
              }}
              refPega={(no) => {
                if (no) pegasRef.current.set(linha.id, no);
                else pegasRef.current.delete(linha.id);
              }}
              pega={{
                onPointerDown: (evento) => aoPremir(evento, indice),
                onPointerMove: aoMoverPonteiro,
                onPointerUp: (evento) => largarPonteiro(evento, { mover: true }),
                onPointerCancel: (evento) => largarPonteiro(evento, { mover: false }),
                onLostPointerCapture: (evento) => largarPonteiro(evento, { mover: false }),
                onKeyDown: (evento) => aoTecla(evento, indice, linha),
                onBlur: aoSairDaPega,
              }}
            />
          );
        })}
      </ol>
    </section>
  );
}

function LinhaParagem({
  idBase,
  linha,
  estilo,
  movida,
  somenteLeitura,
  desligada,
  arrastavel,
  comPega,
  podeArrastar,
  idInstrucoes,
  evitarPortagens,
  acoes,
  refLinha,
  refPega,
  pega,
}) {
  const [aberta, setAberta] = useState(false);
  const nome = nomeDaLinha(linha);
  const motivo = textoDoMotivo(linha);
  const chegada = textoDaChegada(linha);

  return (
    <li
      ref={refLinha}
      className={movida ? 'crm-paragem crm-paragem--arrastada' : 'crm-paragem'}
      style={estilo}
      data-testid="crm-paragem"
    >
      <Collapsible open={aberta} onOpenChange={setAberta}>
        <div className="flex items-start gap-1 p-1">
          {comPega && (
            <button
              ref={refPega}
              type="button"
              className="crm-pega"
              aria-roledescription={ROTULO_PEGA}
              aria-describedby={idInstrucoes}
              aria-label={nome ? `Mover ${nome}` : 'Mover a paragem'}
              disabled={!podeArrastar}
              {...pega}
            >
              <GripVertical className="h-5 w-5" aria-hidden="true" />
            </button>
          )}
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex min-h-11 min-w-0 flex-1 items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <NumeroDaParagem linha={linha} />
              <span className="grid min-w-0 flex-1 gap-0.5">
                <span className="font-semibold leading-snug [overflow-wrap:anywhere]">{nome}</span>
                {motivo && <span className="text-sm text-muted-foreground">{motivo}</span>}
                {chegada && <span className="text-sm text-muted-foreground">{chegada}</span>}
                {linha.textoAviso && <span className="text-sm font-semibold text-amber-700 dark:text-amber-400">{linha.textoAviso}</span>}
              </span>
              <ChevronDown
                className={`mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform ${aberta ? 'rotate-180' : ''}`}
                aria-hidden="true"
              />
            </button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent>
          <Detalhe
            idBase={idBase}
            linha={linha}
            somenteLeitura={somenteLeitura}
            desligada={desligada}
            arrastavel={arrastavel}
            evitarPortagens={evitarPortagens}
            acoes={acoes}
          />
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}
