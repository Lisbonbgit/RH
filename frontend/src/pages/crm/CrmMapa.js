// Mapa das lojas (desenho original §6.1; plano T2.25). Porta do ecrã
// public/assets/js/ecras/mapa.js do CRM autónomo, no aspeto do portal.
//
// Todas as lojas como pinos com a cor da fase e o nome sempre visível, sem
// agrupamento, com a atribuição no canto (o mapa vive em `MapaLojas` e
// `lib/crm/mapa.js`). A rota abre em área cheia, sem as margens do layout
// (`ecraCheioDoCrm`, nas duas casas).
//  - Pede ao mesmo tempo a configuração do mapa, as lojas e as regiões. A
//    primeira vista só se mostra quando as lojas chegam (para não se pedirem
//    mosaicos de duas vistas seguidas); sem elas, o centro das definições, o
//    erro e "Tentar novamente", que volta a pedir só o que falhou.
//  - Filtros de fase e região por cima do mapa, guardados no `localStorage`
//    (`crm.filtros`) e aplicados aqui (`lib/crm/filtros.js`). Uma região
//    guardada que já foi apagada volta a "Todas".
//  - Tocar num pino abre o cartão da loja por baixo do mapa: o mapa encolhe e
//    centra-se na loja. Tocar no mapa fecha o cartão e os filtros; o Escape
//    fecha o cartão e devolve o foco ao pino.
//  - `?loja=<id>` abre o mapa centrado nessa loja, ao nível da rua (procura-se
//    na lista, sem outro pedido). Quem manda voltar ao mapa pode deixar um
//    aviso no `state` da navegação (`{aviso: 'Loja guardada'}`): aparece num
//    toast, com "— os filtros escondem-na do mapa." quando é o caso, e só uma
//    vez (sai do histórico, para não voltar ao recarregar).
// As decisões estão em `lib/crm/ecraMapa.js` (com testes).
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { MapPinPlus } from 'lucide-react';
import { Button } from '../../components/ui/button';
import CartaoLoja from '../../components/crm/CartaoLoja';
import FiltrosMapa from '../../components/crm/FiltrosMapa';
import MapaLojas from '../../components/crm/MapaLojas';
import { baseCrm } from '../../lib/crm/acesso';
import { listarLojas, listarRegioes, obterConfigMapa } from '../../lib/crm/api';
import { ajustarARegioes, aplicarFiltros, carregarFiltros, guardarFiltros } from '../../lib/crm/filtros';
import { MENSAGEM_SEM_MAPA, configuracaoValida } from '../../lib/crm/mapa';
import { PARAMETRO_LOJA, lerAviso, lojaComId, textoAviso, textoDoErro, vistaAoCarregar } from '../../lib/crm/ecraMapa';

const PEDIDOS = { config: obterConfigMapa, lojas: listarLojas, regioes: listarRegioes };
const TODOS = Object.keys(PEDIDOS);

// O localStorage pode não existir ou lançar (browser bloqueado, modo privado): os filtros funcionam na
// mesma, só não ficam guardados (o filtros.js também apanha os erros de leitura e escrita).
function armazenamento() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export default function CrmMapa() {
  const { pathname, search, state } = useLocation();
  const navigate = useNavigate();
  const [parametros] = useSearchParams();
  const base = baseCrm(pathname);
  const idLoja = parametros.get(PARAMETRO_LOJA);

  const [configuracao, setConfiguracao] = useState(null); // o GET /config (null até chegar)
  const [lojas, setLojas] = useState(undefined); // undefined: a carregar; null: falhou; a lista
  const [regioes, setRegioes] = useState(null); // null até chegarem (ou se falharam)
  const [falhas, setFalhas] = useState([]); // [{recurso, erro}], a última no fim
  const [aTentar, setATentar] = useState(false);
  const [leafletFalhou, setLeafletFalhou] = useState(false);
  const [mapa, setMapa] = useState(null); // o mapa do MapaLojas, quando está pronto
  const [filtros, setFiltros] = useState(() => carregarFiltros(armazenamento()));
  const [filtrosAbertos, setFiltrosAbertos] = useState(false);
  const [escolhida, setEscolhida] = useState(null); // a loja do cartão: {loja, marcador}

  const filtrosAtuais = useRef(filtros);
  const geracao = useRef(0); // as respostas de uma montagem que já acabou não contam
  const vistaFeita = useRef(null); // o mapa que já tem uma vista
  const avisoMostrado = useRef(false);
  const nomeDoCartao = useRef(null);
  const focoAoFechar = useRef(null); // o marcador (ou o mapa) que recebe o foco quando o cartão fecha

  // --- Pedidos ------------------------------------------------------------------------------------------

  const carregar = useCallback(async (recursos, minha) => {
    await Promise.all(recursos.map(async (recurso) => {
      let dados;
      try {
        dados = await PEDIDOS[recurso]();
      } catch (erro) {
        if (minha !== geracao.current) return;
        setFalhas((atuais) => [...atuais.filter((f) => f.recurso !== recurso), { recurso, erro }]);
        if (recurso === 'lojas') setLojas(null);
        return;
      }
      if (minha !== geracao.current) return;
      setFalhas((atuais) => atuais.filter((f) => f.recurso !== recurso));
      if (recurso === 'config') {
        setConfiguracao(dados ?? {});
      } else if (recurso === 'lojas') {
        setLojas(Array.isArray(dados) ? dados : []);
      } else {
        // Uma região guardada que já não existe (foi apagada) volta a "Todas" (e fica guardada assim).
        setRegioes(Array.isArray(dados) ? dados : []);
        setFiltros((atuais) => {
          const { filtros: ajustados, mudou } = ajustarARegioes(atuais, dados);
          return mudou ? ajustados : atuais;
        });
      }
    }));
  }, []);

  useEffect(() => {
    geracao.current += 1;
    carregar(TODOS, geracao.current);
    return () => {
      geracao.current += 1;
    };
  }, [carregar]);

  // Volta a pedir só o que falhou; um toque, um pedido.
  async function tentarDeNovo() {
    const minha = geracao.current;
    const recursos = falhas.map((f) => f.recurso);
    if (recursos.includes('lojas')) setLojas(undefined);
    setATentar(true);
    await carregar(recursos, minha);
    if (minha === geracao.current) setATentar(false);
  }

  // --- Filtros ------------------------------------------------------------------------------------------

  useEffect(() => {
    filtrosAtuais.current = filtros;
    guardarFiltros(armazenamento(), filtros);
  }, [filtros]);

  const visiveis = useMemo(() => (Array.isArray(lojas) ? aplicarFiltros(lojas, filtros) : null), [lojas, filtros]);

  // --- O mapa e a vista ---------------------------------------------------------------------------------

  const semMapa = leafletFalhou || (configuracao !== null && !configuracaoValida(configuracao));
  const comMapa = !semMapa && configuracao !== null;

  // Quando as lojas chegam (ou falham), ou o endereço pede outra loja: a vista (lib/crm/ecraMapa.js).
  useEffect(() => {
    if (!mapa || lojas === undefined) return;
    const vista = vistaAoCarregar({ lojas, filtros: filtrosAtuais.current, idLoja, jaTemVista: vistaFeita.current === mapa });
    vistaFeita.current = mapa;
    if (vista?.tipo === 'centrar') mapa.centrarEm(vista.loja, vista.zoom);
    else if (vista?.tipo === 'enquadrar') mapa.enquadrar(vista.lojas);
  }, [mapa, lojas, idLoja]);

  // O aviso de quem mandou voltar ao mapa, quando já se sabe se os filtros escondem a loja do endereço.
  useEffect(() => {
    const aviso = lerAviso(state);
    if (aviso === null || avisoMostrado.current || lojas === undefined) return;
    avisoMostrado.current = true;
    toast.success(textoAviso(aviso, lojaComId(lojas, idLoja), filtrosAtuais.current));
    navigate({ pathname, search }, { replace: true, state: null });
  }, [state, lojas, idLoja, pathname, search, navigate]);

  // --- O cartão da loja ---------------------------------------------------------------------------------

  const fecharCartao = useCallback(({ devolverFoco = false } = {}) => {
    if (!escolhida) return;
    if (devolverFoco) focoAoFechar.current = escolhida.marcador ?? 'mapa';
    setEscolhida(null);
  }, [escolhida]);

  // Esconder pelos filtros a loja do cartão fecha-o.
  useEffect(() => {
    if (escolhida && visiveis && !visiveis.some((l) => l.id === escolhida.loja.id)) setEscolhida(null);
  }, [escolhida, visiveis]);

  // O cartão abre (ou troca de loja) ou fecha: o mapa volta a medir a área (que encolheu ou cresceu) e,
  // aberto, centra-se na loja e o foco vai para o nome; fechado com o Escape ou o "Fechar", volta ao pino
  // (ou ao mapa, se o pino já não está na página porque os filtros mudaram).
  useLayoutEffect(() => {
    if (!mapa) return;
    mapa.redimensionar();
    if (escolhida) {
      mapa.centrarEm(escolhida.loja);
      nomeDoCartao.current?.focus();
      return;
    }
    const alvo = focoAoFechar.current;
    focoAoFechar.current = null;
    if (!alvo) return;
    const pino = alvo === 'mapa' ? null : alvo.getElement?.();
    if (pino?.isConnected) pino.focus();
    else mapa.mapa.getContainer().focus();
  }, [mapa, escolhida]);

  const escolherLoja = useCallback((loja, marcador) => setEscolhida({ loja, marcador }), []);

  const tocarNoMapa = useCallback(() => {
    fecharCartao();
    setFiltrosAbertos(false);
  }, [fecharCartao]);

  // Escape: fecha o cartão. Com o painel dos filtros aberto, é o painel que o trata (e fica por aí).
  function aoCarregarNumaTecla(evento) {
    if (evento.key !== 'Escape' || evento.defaultPrevented || !escolhida) return;
    fecharCartao({ devolverFoco: true });
  }

  // --- Ecrã ---------------------------------------------------------------------------------------------

  let mensagem = null;
  if (semMapa) mensagem = MENSAGEM_SEM_MAPA;
  else if (falhas.length > 0) mensagem = textoDoErro(falhas[falhas.length - 1].erro);

  return (
    // O Escape sobe dos filhos (pinos, cartão) até aqui; a secção em si não recebe o foco.
    <section className="flex h-full flex-col" onKeyDown={aoCarregarNumaTecla} data-testid="crm-ecra-mapa">
      <h1 className="sr-only">Mapa</h1>

      {mensagem && (
        <div role="alert" className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-4 py-2.5">
          <p className="min-w-0 flex-1 text-sm font-medium text-destructive">{mensagem}</p>
          {!semMapa && (
            <Button type="button" variant="outline" className="h-11" onClick={tentarDeNovo} disabled={aTentar}>
              Tentar novamente
            </Button>
          )}
        </div>
      )}

      <div className="crm-mapa__vista bg-muted">
        {comMapa && (
          <>
            <MapaLojas
              configuracao={configuracao}
              lojas={visiveis}
              ocupado={lojas === undefined}
              aoPronto={setMapa}
              aoFalhar={() => setLeafletFalhou(true)}
              aoEscolherLoja={escolherLoja}
              aoTocarNoMapa={tocarNoMapa}
            />
            <div className="crm-mapa__barra">
              <FiltrosMapa
                filtros={filtros}
                regioes={regioes}
                contagem={visiveis === null ? null : visiveis.length}
                aberto={filtrosAbertos}
                aoAbrir={setFiltrosAbertos}
                aoMudar={setFiltros}
              />
              <Button asChild className="h-11 shadow-md">
                <Link to={`${base}/lojas/nova`} aria-label="Nova loja" data-testid="crm-mapa-nova-loja">
                  <MapPinPlus className="h-4 w-4" aria-hidden="true" />
                  <span className="hidden sm:inline">Nova loja</span>
                </Link>
              </Button>
            </div>
          </>
        )}
      </div>

      {escolhida && (
        <CartaoLoja
          loja={escolhida.loja}
          base={base}
          aoFechar={() => fecharCartao({ devolverFoco: true })}
          refNome={nomeDoCartao}
        />
      )}
    </section>
  );
}
