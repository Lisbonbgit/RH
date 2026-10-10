// O seletor da localização de uma loja (desenho original §6.2; plano T2.26):
// um mapa onde se toca para pôr o pino, que se arrasta até ao sítio exato e se
// confirma com "Confirmar localização"; por cima, a pesquisa de morada e
// "Estou nesta loja". Porta de
// public/assets/js/componentes/seletor-localizacao.js do CRM autónomo, no
// aspeto do portal. Serve a nova loja (T2.27), a ficha ("Corrigir
// localização", T2.28) e o ponto da fábrica (T2.30, sem GPS).
//
// As regras estão em `lib/crm/seletor.js` (com testes); aqui só se ligam ao
// React, no molde do `MapaLojas`:
//  - o seletor (e o mapa) cria-se num `useEffect`, com a área já na página, e
//    destrói-se no cleanup (o `StrictMode` monta duas vezes em
//    desenvolvimento). O cleanup também cancela a pesquisa de morada e faz o
//    GPS e a morada sugerida que chegarem depois não mexerem em nada;
//  - `configuracao` é a do GET /api/crm/config: `undefined` enquanto chega
//    (sem mapa ainda), e `null` ou inválida dá "Não foi possível carregar o
//    mapa — recarregue a página.". Tem de ser o mesmo objeto entre desenhos:
//    um objeto novo cria outro mapa (e o pino perde-se);
//  - `inicial` ({lat, lng, origem, precisao_m?}: a localização que a loja já
//    tem, ou o ponto da fábrica), `comGps`, `textos` e `focarAoIniciar` leem-se
//    ao criar. Com `focarAoIniciar` (a ficha, ao abrir "Corrigir localização":
//    o botão em que se tocou desaparece), o foco vai para "Confirmar
//    localização" assim que o mapa existe;
//  - o GPS só se pede ao tocar em "Estou nesta loja" (`navigator.geolocation`,
//    nunca ao montar), e o botão fica com `aria-disabled` enquanto espera (o
//    foco não se perde);
//  - `aoMudar(localizacao)`: a localização confirmada ({lat, lng,
//    origem_coords, precisao_m}, o bloco que a API recebe) ou `null`;
//    `aoEscolherMorada(sugestao)` e `aoSugerirMorada(sugestao)` deixam o ecrã
//    preencher a morada (`camposDaMorada` / `camposSugeridos` de `morada.js`);
//  - pela `ref`: `mostrarErro(texto)` / `limparErro()` (ex.: o 422 "Fora de
//    Portugal" do servidor), `desconfirmar()`, `focar()` e `colocar(ponto)`;
//  - quando a área muda de tamanho, o Leaflet volta a medi-la.
// O pino não leva HTML (a gota é do `crm.css`), e os textos dos dados (a
// morada sugerida, as sugestões) entram como texto.
import React, {
  forwardRef, useEffect, useId, useImperativeHandle, useLayoutEffect, useRef, useState,
} from 'react';
import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Check, Loader2, LocateFixed, TriangleAlert } from 'lucide-react';
import { Button } from '../ui/button';
import PesquisaMorada, { Partes } from './PesquisaMorada';
import { moradaInversa, pesquisarMorada } from '../../lib/crm/api';
import {
  criarSeletor, textosSeletor, TEXTO_A_OBTER_LOCALIZACAO, TEXTO_ALTERAR, TEXTO_CONFIRMAR,
} from '../../lib/crm/seletor';
import './crm.css';

// As chamadas da morada do portal (GET /api/crm/morada/pesquisa e /inversa).
const API_MORADA = Object.freeze({
  pesquisarMorada: (parametros) => pesquisarMorada(parametros),
  moradaInversa: (parametros) => moradaInversa(parametros),
});

// O GPS do browser (lê-se o objeto; a posição só se pede ao tocar no botão).
function geolocalizacao() {
  try {
    return typeof navigator === 'undefined' ? undefined : navigator.geolocation;
  } catch {
    return undefined;
  }
}

// A vista antes de haver seletor (configuração a chegar): a mesma de um seletor sem mapa ainda. Criar o
// seletor não toca no mapa, no GPS nem na rede.
const vistaInicial = ({ textos, comGps }) => criarSeletor({
  configuracao: null, textos, api: API_MORADA, geolocation: comGps ? geolocalizacao() : undefined,
}).vista;

const SeletorLocalizacao = forwardRef(function SeletorLocalizacao({
  configuracao, inicial = null, comGps = false, textos, focarAoIniciar = false, aoMudar, aoEscolherMorada,
  aoSugerirMorada,
}, ref) {
  const id = useId();
  const idTitulo = `${id}-titulo`;
  const idErro = `${id}-erro`;
  const rotulos = textosSeletor(textos);
  const area = useRef(null);
  const botaoConfirmar = useRef(null);
  const botaoAlterar = useRef(null);
  const [seletor, setSeletor] = useState(null);
  const [vista, setVista] = useState(() => vistaInicial({ textos, comGps }));
  // O botão que deve receber o foco quando o ecrã já o mostrar (o que se carregou pode ter desaparecido).
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

  // O que se lê ao criar o seletor e as funções mais recentes do ecrã (o seletor cria-se uma vez).
  const opcoes = useRef({});
  useLayoutEffect(() => {
    opcoes.current = {
      inicial, comGps, textos, focarAoIniciar, aoMudar, aoEscolherMorada, aoSugerirMorada,
    };
  });

  useEffect(() => {
    if (configuracao === undefined) return undefined; // a configuração ainda não chegou
    const elemento = area.current;
    let ativo = true;
    const {
      inicial: ponto, comGps: gps, textos: proprios, focarAoIniciar: focar,
    } = opcoes.current;
    const criado = criarSeletor({
      L,
      documento: document,
      configuracao,
      textos: proprios,
      api: API_MORADA,
      geolocation: gps ? geolocalizacao() : undefined,
      aoMudar: (localizacao) => opcoes.current.aoMudar?.(localizacao),
      aoEscolherMorada: (sugestao) => opcoes.current.aoEscolherMorada?.(sugestao),
      aoSugerirMorada: (sugestao) => opcoes.current.aoSugerirMorada?.(sugestao),
      aoMudarVista: (nova) => {
        if (ativo) setVista(nova);
      },
      aoFocar: (alvo) => {
        if (!ativo) return;
        focoPendente.current = alvo;
        setPedidosDeFoco((n) => n + 1);
      },
    });
    const comMapa = criado.iniciar(elemento, { inicial: ponto ?? undefined });
    setVista(criado.vista);
    if (comMapa && focar) criado.focar();
    setSeletor(criado);

    const observador = typeof ResizeObserver === 'function' ? new ResizeObserver(() => criado.redimensionar()) : null;
    observador?.observe(elemento);

    return () => {
      ativo = false;
      observador?.disconnect();
      setSeletor(null);
      criado.destruir();
    };
  }, [configuracao]);

  // O foco pedido pelo seletor, depois de o React mostrar o botão.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    (alvo === 'alterar' ? botaoAlterar : botaoConfirmar).current?.focus();
  }, [pedidosDeFoco, vista]);

  useImperativeHandle(ref, () => ({
    mostrarErro: (texto) => seletor?.mostrarErro(texto),
    limparErro: () => seletor?.limparErro(),
    desconfirmar: () => seletor?.desconfirmar(),
    focar: () => seletor?.focar(),
    colocar: (ponto, opcoesColocar) => seletor?.colocar(ponto, opcoesColocar) ?? false,
    get localizacao() {
      return seletor?.localizacao ?? null;
    },
  }), [seletor]);

  const confirmado = vista.estado === 'confirmado';
  const { gps } = vista;
  let classeDica = 'text-muted-foreground';
  if (confirmado) classeDica = 'text-success-strong';
  else if (vista.aviso) classeDica = 'text-warning-strong';

  return (
    <section
      aria-labelledby={idTitulo}
      className="crm-seletor space-y-3"
      data-estado={vista.estado}
      data-testid="crm-seletor"
    >
      <h2 id={idTitulo} className="font-heading text-lg font-semibold">{rotulos.titulo}</h2>

      {vista.pesquisa && (
        <PesquisaMorada
          id={`${id}-pesquisa`}
          vista={vista.pesquisa}
          desativado={!seletor}
          aoEscrever={(valor) => seletor?.pesquisa?.escrever(valor)}
          aoTecla={(tecla) => seletor?.pesquisa?.tecla(tecla) ?? false}
          aoEscolher={(indice) => seletor?.pesquisa?.escolher(indice)}
        />
      )}

      {gps && (
        <div className="space-y-1.5">
          <Button
            type="button"
            variant="outline"
            className="h-11 w-full sm:w-auto aria-disabled:cursor-wait aria-disabled:opacity-70"
            aria-disabled={gps.ocupado ? 'true' : undefined}
            onClick={() => seletor?.estouNestaLoja()}
            data-testid="crm-seletor-gps"
          >
            {gps.texto === TEXTO_A_OBTER_LOCALIZACAO
              ? <Loader2 className="animate-spin" aria-hidden="true" />
              : <LocateFixed aria-hidden="true" />}
            {gps.texto}
          </Button>
          {/* Sempre na página (mesmo vazias), para os leitores de ecrã lerem o que lá aparecer. */}
          <p
            aria-live="polite"
            className={`text-sm [overflow-wrap:anywhere] ${gps.mensagem ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}
            data-testid="crm-seletor-gps-estado"
          >
            {gps.mensagem?.texto ?? ''}
          </p>
          <p
            aria-live="polite"
            className={`text-sm [overflow-wrap:anywhere] ${vista.moradaSugerida?.tipo === 'erro' ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}
            data-testid="crm-seletor-morada-sugerida"
          >
            {vista.moradaSugerida && <Partes partes={vista.moradaSugerida.partes} />}
          </p>
        </div>
      )}

      <p
        aria-live="polite"
        className={`flex items-start gap-1.5 text-sm font-semibold ${classeDica}`}
        data-aviso={vista.aviso ?? undefined}
        data-testid="crm-seletor-dica"
      >
        {confirmado && <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />}
        {vista.aviso && <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />}
        <span>{vista.dica}</span>
      </p>

      <div
        className={`crm-seletor__vista rounded-md border bg-muted ${confirmado ? 'border-success ring-1 ring-success' : ''}`}
      >
        <div
          ref={area}
          className="crm-mapa"
          role="region"
          aria-label={rotulos.mapa}
          aria-describedby={vista.erro ? idErro : undefined}
          aria-busy={configuracao === undefined ? 'true' : undefined}
        />
      </div>

      {vista.erro && (
        <p id={idErro} role="alert" className="text-sm font-semibold text-destructive" data-testid="crm-seletor-erro">
          {vista.erro}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {confirmado ? (
          <Button
            ref={botaoAlterar}
            type="button"
            variant="outline"
            className="h-11 flex-1 sm:flex-none"
            onClick={() => seletor?.alterar()}
            data-testid="crm-seletor-alterar"
          >
            {TEXTO_ALTERAR}
          </Button>
        ) : (
          <Button
            ref={botaoConfirmar}
            type="button"
            className="h-11 flex-1 sm:flex-none"
            disabled={!vista.confirmarAtivo}
            onClick={() => seletor?.confirmar()}
            data-testid="crm-seletor-confirmar"
          >
            {TEXTO_CONFIRMAR}
          </Button>
        )}
      </div>
    </section>
  );
});

export default SeletorLocalizacao;
