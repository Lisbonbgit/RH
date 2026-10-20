// O seletor da localização de uma loja (desenho original §6.2; plano T2.26), sobre o Google Maps desde a G14
// do plano do mapa Google (adenda §1.2 e §6.3): um mapa onde se toca para pôr o pino, que se arrasta até ao
// sítio exato e se confirma com "Confirmar localização"; por cima, a pesquisa da Google e "Estou nesta loja".
// Porta de public/assets/js/componentes/seletor-localizacao.js do CRM autónomo, no aspeto do portal. Serve a
// nova loja (T2.27), a ficha ("Corrigir localização", T2.28) e o ponto da fábrica (T2.30, sem GPS).
//
// As regras estão em `lib/crm/seletor.js` (com testes); aqui só se ligam ao React, no molde do `MapaLojas`:
//  - `configuracao` é a do GET /api/crm/config: `undefined` enquanto chega (sem mapa ainda). Com a chave e o
//    Map ID, a Google carrega-se primeiro pelo nosso carregador (`lib/crm/carregadorGoogle.js`: o mapa, os
//    pinos e os lugares, pedidos no mesmo instante, num só script) e só depois se cria o seletor; sem eles,
//    nada se pede e o seletor diz porquê ("Mapa não configurado…" com `google: null`, "Não foi possível
//    carregar o mapa…" se for `null` ou inválida, ou se a Google não carregar). Tem de ser o mesmo objeto
//    entre desenhos: um objeto novo cria outro mapa (e o pino perde-se);
//  - o seletor (e o mapa) cria-se num `useEffect` e destrói-se no cleanup. O `StrictMode` monta duas vezes em
//    desenvolvimento: a montagem já desfeita não cria nada quando a Google chega (`ativo`). O cleanup também
//    faz o GPS, a morada sugerida, a posição de um negócio e a escolha da pesquisa que chegarem depois não
//    mexerem em nada;
//  - `inicial` ({lat, lng, origem, precisao_m?, google_place_id?}: a localização que a loja já tem, ou o ponto
//    da fábrica), `comGps`, `textos` e `focarAoIniciar` leem-se ao criar. Com `focarAoIniciar` (a ficha, ao
//    abrir "Corrigir localização": o botão em que se tocou desaparece), o foco vai para "Confirmar
//    localização" assim que o mapa existe;
//  - o GPS só se pede ao tocar em "Estou nesta loja" (`navigator.geolocation`, nunca ao montar), e o botão fica
//    com `aria-disabled` enquanto espera (o foco não se perde);
//  - a pesquisa da Google (`PesquisaLugar`): o seletor cria o elemento com o mapa e este componente põe-no na
//    página, fora da caixa do mapa. Escolher uma morada põe lá o pino (por arrastar até à porta da loja),
//    mostra "Morada sugerida: …" e chama `aoEscolherMorada`;
//  - tocar no ícone de um negócio do mapa abre o balão da própria Google e, entre a dica e o mapa, o painel
//    "Negócio selecionado" (`NegocioSelecionado`, com "Pôr o pino neste negócio" e "Fechar"; o foco vai para o
//    título dele). Ao fechar, se o foco estava lá e se perdeu, volta ao mapa;
//  - `aoMudar(localizacao)`: a localização confirmada ({lat, lng, origem_coords, precisao_m, google_place_id},
//    o bloco que a API recebe) ou `null`; `aoEscolherMorada(morada)` (a pesquisa da Google) e
//    `aoSugerirMorada(sugestao)` (o GPS) deixam o ecrã preencher a morada (`camposDaMorada` /
//    `camposSugeridos` de `morada.js`);
//  - `aoPronto(seletor | null)`: o seletor tem mapa e a `ref` já o usa (a nova loja chama daqui o
//    `usarNegocio` do negócio com que chegou); `null` quando sai;
//  - pela `ref`: `mostrarErro(texto)` / `limparErro()` (ex.: o 422 "Fora de Portugal" do servidor),
//    `desconfirmar()`, `focar()`, `colocar(ponto)`, `escolherNegocio`, `usarNegocio`, `fecharNegocio`,
//    `limitesDoMapa` e `localizacao`;
//  - quando a área muda de tamanho, o mapa volta a medi-la.
// O `div.crm-mapa` não tem filhos nossos (a Google enche-o com o mapa, o logótipo e a atribuição, que nada
// nosso tapa); o pino não leva HTML (a gota é do `crm.css`), e os textos dos dados (a morada sugerida) entram
// como texto.
import React, {
  forwardRef, useEffect, useId, useImperativeHandle, useLayoutEffect, useRef, useState,
} from 'react';
import { Check, Loader2, LocateFixed, TriangleAlert } from 'lucide-react';
import { Button } from '../ui/button';
import NegocioSelecionado from './NegocioSelecionado';
import { Partes } from './Partes';
import PesquisaLugar from './PesquisaLugar';
import { moradaInversa } from '../../lib/crm/api';
import { prepararGoogleMaps } from '../../lib/crm/carregadorGoogle';
import { TEXTO_USAR_ESTE_NEGOCIO } from '../../lib/crm/lugarGoogle';
import { configuracaoValida } from '../../lib/crm/mapa';
import {
  criarSeletor, textosSeletor, TEXTO_A_OBTER_LOCALIZACAO, TEXTO_ALTERAR, TEXTO_CONFIRMAR,
} from '../../lib/crm/seletor';
import './crm.css';

// As bibliotecas da Google de que o seletor precisa (a dos lugares serve a pesquisa e o negócio selecionado).
const BIBLIOTECAS = ['maps', 'marker', 'places'];

// A morada do ponto do GPS (GET /api/crm/morada/inversa).
const API_MORADA = Object.freeze({
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

// A vista antes de haver seletor (configuração ou Google a chegar): a mesma de um seletor sem mapa ainda.
// Criar o seletor não toca no mapa, no GPS nem na rede.
const vistaInicial = ({ textos, comGps }) => criarSeletor({
  configuracao: null, textos, api: API_MORADA, geolocation: comGps ? geolocalizacao() : undefined,
}).vista;

// O foco perdeu-se (o elemento que o tinha saiu da página).
const focoPerdido = () => !document.activeElement || document.activeElement === document.body;

const SeletorLocalizacao = forwardRef(function SeletorLocalizacao({
  configuracao, inicial = null, comGps = false, textos, focarAoIniciar = false, aoMudar, aoEscolherMorada,
  aoSugerirMorada, aoPronto,
}, ref) {
  const id = useId();
  const idTitulo = `${id}-titulo`;
  const idErro = `${id}-erro`;
  const rotulos = textosSeletor(textos);
  const area = useRef(null);
  const botaoConfirmar = useRef(null);
  const botaoAlterar = useRef(null);
  const tituloNegocio = useRef(null);
  const [seletor, setSeletor] = useState(null);
  const [vista, setVista] = useState(() => vistaInicial({ textos, comGps }));
  // O botão que deve receber o foco quando o ecrã já o mostrar (o que se carregou pode ter desaparecido).
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

  // O que se lê ao criar o seletor e as funções mais recentes do ecrã (o seletor cria-se uma vez).
  const opcoes = useRef({});
  useLayoutEffect(() => {
    opcoes.current = {
      inicial, comGps, textos, focarAoIniciar, aoMudar, aoEscolherMorada, aoSugerirMorada, aoPronto,
    };
  });

  useEffect(() => {
    if (configuracao === undefined) return undefined; // a configuração ainda não chegou
    const elemento = area.current;
    // Falso depois do cleanup: o que chegar depois (a Google, uma falha) já não é desta montagem.
    let ativo = true;
    let criado = null;
    let observador = null;
    const {
      inicial: ponto, comGps: gps, textos: proprios, focarAoIniciar: focar,
    } = opcoes.current;

    // Sem `google` (não configurado, inválido, ou a Google não carregou), o seletor diz que não há mapa.
    function criar(google) {
      criado = criarSeletor({
        google,
        documento: document,
        configuracao,
        textos: proprios,
        api: API_MORADA,
        geolocation: gps ? geolocalizacao() : undefined,
        aoMudar: (localizacao) => opcoes.current.aoMudar?.(localizacao),
        aoEscolherMorada: (morada) => opcoes.current.aoEscolherMorada?.(morada),
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
      observador = typeof ResizeObserver === 'function' ? new ResizeObserver(() => criado.redimensionar()) : null;
      observador?.observe(elemento);
    }

    async function montar() {
      let google;
      if (configuracaoValida(configuracao)) {
        try {
          const { importar } = prepararGoogleMaps({
            janela: window,
            documento: document,
            chave: configuracao.google.chave,
          });
          await Promise.all(BIBLIOTECAS.map((nome) => importar(nome)));
          google = window.google;
        } catch (erro) {
          if (!ativo) return;
          console.error('[crm] o mapa não foi criado:', erro);
        }
      }
      if (ativo) criar(google);
    }
    montar();

    return () => {
      ativo = false;
      if (!criado) return;
      observador?.disconnect();
      setSeletor(null);
      criado.destruir();
    };
  }, [configuracao]);

  // O seletor com mapa já está na `ref`: a página pode usá-lo (e sabe quando deixa de poder).
  useEffect(() => {
    if (!seletor?.mapa) return undefined;
    opcoes.current.aoPronto?.(seletor);
    return () => opcoes.current.aoPronto?.(null);
  }, [seletor]);

  // O foco pedido pelo seletor, depois de o React mostrar o botão.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    (alvo === 'alterar' ? botaoAlterar : botaoConfirmar).current?.focus();
  }, [pedidosDeFoco, vista]);

  // O painel do negócio: ao abrir (um toque num negócio do mapa), o foco vai para o título dele; ao fechar, se
  // o foco esteve lá dentro e se perdeu com ele (a ação ou o "Fechar" saíram da página), volta ao mapa. A nova
  // loja que chega com um negócio não mexe no foco (o painel nunca o teve).
  const estadoNegocio = vista.negocio.estado;
  const estadoNegocioAntes = useRef(estadoNegocio);
  const painelTeveFoco = useRef(false);
  useLayoutEffect(() => {
    const antes = estadoNegocioAntes.current;
    estadoNegocioAntes.current = estadoNegocio;
    if (antes === 'fechado' && estadoNegocio === 'aberto') {
      tituloNegocio.current?.focus();
    } else if (antes !== 'fechado' && estadoNegocio === 'fechado') {
      if (painelTeveFoco.current && focoPerdido()) seletor?.mapa?.focar();
      painelTeveFoco.current = false;
    }
  }, [estadoNegocio, seletor]);

  useImperativeHandle(ref, () => ({
    mostrarErro: (texto) => seletor?.mostrarErro(texto),
    limparErro: () => seletor?.limparErro(),
    desconfirmar: () => seletor?.desconfirmar(),
    focar: () => seletor?.focar(),
    colocar: (ponto, opcoesColocar) => seletor?.colocar(ponto, opcoesColocar) ?? false,
    escolherNegocio: (placeId, opcoesNegocio) => seletor?.escolherNegocio(placeId, opcoesNegocio),
    usarNegocio: (placeId, opcoesNegocio) => seletor?.usarNegocio(placeId, opcoesNegocio) ?? Promise.resolve(false),
    fecharNegocio: () => seletor?.fecharNegocio(),
    limitesDoMapa: () => seletor?.limitesDoMapa() ?? null,
    get localizacao() {
      return seletor?.localizacao ?? null;
    },
  }), [seletor]);

  const confirmado = vista.estado === 'confirmado';
  const { gps, pesquisa } = vista;
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

      {pesquisa.elemento && <PesquisaLugar id={`${id}-pesquisa`} elemento={pesquisa.elemento} ativa={pesquisa.ativa} />}

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
          {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
          <p
            aria-live="polite"
            className={`text-sm [overflow-wrap:anywhere] ${gps.mensagem ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}
            data-testid="crm-seletor-gps-estado"
          >
            {gps.mensagem?.texto ?? ''}
          </p>
        </div>
      )}

      {/* A morada sugerida (do GPS ou da pesquisa): sempre na página enquanto um dos dois existe. */}
      {(gps || pesquisa.ativa) && (
        <p
          aria-live="polite"
          className={`text-sm [overflow-wrap:anywhere] ${vista.moradaSugerida?.tipo === 'erro' ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}
          data-testid="crm-seletor-morada-sugerida"
        >
          {vista.moradaSugerida && <Partes partes={vista.moradaSugerida.partes} />}
        </p>
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

      {estadoNegocio !== 'fechado' && (
        // Só para saber se o foco esteve no painel (o onFocus do React apanha o dos botões e o do título).
        <div onFocus={() => { painelTeveFoco.current = true; }}>
          <NegocioSelecionado
            estado={estadoNegocio}
            mensagem={vista.negocio.mensagem}
            acao={{ texto: TEXTO_USAR_ESTE_NEGOCIO, aoTocar: () => seletor?.usarNegocio() }}
            aoFechar={() => seletor?.fecharNegocio()}
            refTitulo={tituloNegocio}
          />
        </div>
      )}

      <div
        className={`crm-seletor__vista rounded-md border bg-muted ${confirmado ? 'border-success ring-1 ring-success' : ''}`}
      >
        <div
          ref={area}
          className="crm-mapa"
          role="region"
          aria-label={rotulos.mapa}
          aria-describedby={vista.erro ? idErro : undefined}
          aria-busy={seletor ? undefined : 'true'}
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
