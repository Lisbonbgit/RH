// O planeador da rota de um dia, em `rotas/:data` (plano F3 T3.38/T3.39; desenho original §7). As regras estão em
// `lib/crm/planeador.js` (o controlador, com testes) e em `lib/crm/painelRota.js`: esta página cria o
// planeador num `useEffect` (e o `destruir()` no retorno: as respostas atrasadas, a rede e a espera das horas
// já não mudam nada), desenha a `vista` que ele entrega e passa-lhe o que a pessoa faz.
//  - Disposição (`crm.css`, `.crm-planeador`): o painel (até 440 px) ao lado do mapa a partir de 1024 px, e
//    abaixo disso o mapa com altura fixa em cima e o painel por baixo, tudo a deslocar-se. O painel tem o
//    título, a faixa da leitura só ("Concluída — só de leitura"), a do conflito ("Alterado por outra pessoa —
//    recarregar", com "Recarregar"), o alerta da última gravação recusada, o `ResumoRota` (estado, totais,
//    avisos, botões com o motivo, blocos do Google), as `DefinicoesDoDia` (fechadas, com o resumo), as secções
//    da `ListaParagens` ("Rota", "⚠️ Fechadas neste dia", "⚠️ Não cabem no horário", "Lojas apagadas"), as
//    `SugestoesRota` (depois das paragens: a lista pode ser longa) e, num bloco próprio no fim, a atribuição do
//    openrouteservice (`RodapeOrs`).
//  - O mapa é o `MapaLojas` com a classe `crm-mapa--planeador` (as lojas fora da rota esbatidas), as lojas
//    fora da rota, a rota (`vista.mapa`: os pinos numerados, o início e o fim e a linha) e os negócios da
//    Google não clicáveis. Nada nosso fica dentro nem por cima dele (a regra de disposição): a falha das
//    lojas ou da configuração fica numa faixa por cima da área do mapa, que encolhe. Sem a chave Google no
//    servidor (ou se a Google não carregar), a mensagem no lugar do mapa; o resto do planeador funciona. O
//    mapa enquadra a rota uma vez, quando fica pronto; o toque num pino de uma paragem leva à linha dela.
//  - O mapa também escolhe (T3.39): com "Ponto no mapa" nas definições, a faixa "Toque no mapa no ponto de
//    início" (com "Cancelar") fica por cima da área do mapa (que encolhe; no telemóvel a área põe-se à vista) e
//    o toque seguinte no mapa é o ponto (`tocarNoMapa`). Um toque numa loja esbatida abre, por baixo da área do
//    mapa, o cartão pequeno "Adicionar à rota" (`escolherLoja`): o mapa centra-se na loja e o foco vai para o
//    nome; ao fechar (o "Fechar", o Escape, a loja que entrou na rota) o foco volta ao pino ou ao mapa. Os
//    negócios da Google não respondem (`negociosClicaveis={false}`): um toque neles é um toque no mapa. O
//    Escape também cancela o "Ponto no mapa".
//  - Leitura só (um dia passado, registos do motorista): sem botões nem pegas; os links ficam.
//  - "Dia inválido" (um dia que não existe, ou que o servidor recusa) e a falha da rota ("Tentar novamente")
//    mostram-se sozinhos, com a ligação às Rotas. Com um dia que existe a página ocupa a área toda, sem as
//    margens do layout (`ecraCheioDoCrm`): estas mensagens põem as suas e deslocam-se.
// Mudar de dia (ou de casa: `/crm`, `/admin/crm`) cria o planeador de novo, com a vista do dia novo desde o
// primeiro desenho (a `key`). Os dados entram como texto (o React escapa-os).
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { ChevronLeft, Crosshair, Route as IconeRota } from 'lucide-react'; // nunca `Route`: confundia-se com o `Route` do React Router
import PageHeader from '../../components/PageHeader';
import { Button } from '../../components/ui/button';
import DefinicoesDoDia from '../../components/crm/DefinicoesDoDia';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import ListaParagens from '../../components/crm/ListaParagens';
import MapaLojas from '../../components/crm/MapaLojas';
import ResumoRota, { RodapeOrs } from '../../components/crm/ResumoRota';
import SugestoesRota, { CartaoLojaEscolhida } from '../../components/crm/SugestoesRota';
import { baseCrm, ecraCheioDoCrm } from '../../lib/crm/acesso';
import {
  adicionarParagem, alterarRota, listarLojas, obterConfigMapa, obterRota, obterSugestoes, otimizarRota, recalcularHoras,
} from '../../lib/crm/api';
import { configuracaoDoMapa, mensagemSemMapa } from '../../lib/crm/ecraMapa';
import {
  TEXTO_A_RECARREGAR, TEXTO_CANCELAR, TEXTO_RECARREGAR, TEXTO_ROTAS, TEXTO_TENTAR_DE_NOVO, TEXTO_VOLTAR_AS_ROTAS,
  TITULO_PAINEL, faixaDoPonto, seccoesDoPainel,
} from '../../lib/crm/painelRota';
import { TEXTO_A_CARREGAR, criarPlaneador } from '../../lib/crm/planeador';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  obterRota: (data) => obterRota(data),
  obterConfigMapa: () => obterConfigMapa(),
  listarLojas: () => listarLojas(),
  obterSugestoes: (data) => obterSugestoes(data),
  adicionarParagem: (data, corpo) => adicionarParagem(data, corpo),
  alterarRota: (data, corpo) => alterarRota(data, corpo),
  recalcularHoras: (data, versao) => recalcularHoras(data, versao),
  otimizarRota: (data, versao) => otimizarRota(data, versao),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const avisar = (texto) => toast.success(texto);

// "Dia inválido" e a falha da rota: a mensagem e o que se pode fazer.
function Mensagem({ titulo, mensagem, caminhoRotas, children }) {
  return (
    <div className="mx-auto max-w-3xl space-y-6 animate-fade-in">
      <PageHeader icon={IconeRota} title={titulo} subtitle="CRM Purple House" />
      <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
        <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-rota-falha">
          {mensagem}
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          {children}
          <Button asChild variant="outline" className="h-11">
            <Link to={caminhoRotas} data-testid="crm-rota-voltar">{TEXTO_VOLTAR_AS_ROTAS}</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

function PlaneadorDoDia({ data, base, cheio }) {
  const navigate = useNavigate();
  // O `navigate` do React Router muda com o caminho: o planeador lê sempre o mais recente.
  const navegar = useRef(navigate);
  useEffect(() => {
    navegar.current = navigate;
  }, [navigate]);
  const [planeador, setPlaneador] = useState(null);
  // A primeira vista, antes de o planeador existir: a de um planeador acabado de criar (não pede nada; o
  // `iniciar()` entrega a seguinte).
  const [vista, setVista] = useState(() => criarPlaneador({ data, base }).vista);
  const [mapa, setMapa] = useState(null); // o mapa do MapaLojas, quando está pronto
  const [mapaFalhou, setMapaFalhou] = useState(false); // a Google não carregou ou o mapa não se criou
  const painel = useRef(null);
  const areaDoMapa = useRef(null);
  const tituloDoCartao = useRef(null);
  // O último pino de loja tocado ({loja, marcador}): para centrar o mapa nela e lhe devolver o foco.
  const tocada = useRef(null);

  useEffect(() => {
    const criado = criarPlaneador({
      api: API,
      rede: REDE,
      data,
      base,
      navegar: (caminho, opcoes) => navegar.current(caminho, opcoes),
      aoMudarVista: setVista,
      aoAvisar: avisar,
    });
    setPlaneador(criado);
    criado.iniciar();
    return () => criado.destruir();
  }, [data, base]);

  // A rota enquadra-se uma vez por mapa, quando ele fica pronto (o mapa só existe com a rota, e o MapaLojas já
  // a mostrou: os efeitos dele correm antes dos desta página); depois a pessoa é que mexe no mapa.
  useEffect(() => {
    mapa?.enquadrarRota();
  }, [mapa]);

  // O toque num pino de uma paragem: a linha dela no painel fica à vista e com o foco.
  const escolherParagem = useCallback((paragem) => {
    const linhas = painel.current ? [...painel.current.querySelectorAll('[data-paragem]')] : [];
    const linha = linhas.find((no) => no.dataset.paragem === paragem?.id);
    if (!linha) return;
    linha.scrollIntoView?.({ block: 'nearest' });
    linha.querySelector('button[aria-expanded]')?.focus({ preventScroll: true });
  }, []);

  // "Ponto no mapa": a área do mapa à vista (no telemóvel o planeador desloca-se e o mapa está em cima).
  const pontaAEscolher = vista.escolherPonto;
  useEffect(() => {
    if (pontaAEscolher !== null) areaDoMapa.current?.scrollIntoView?.({ block: 'nearest' });
  }, [pontaAEscolher]);

  // O cartão de uma loja esbatida abre (o mapa centra-se nela e o foco vai para o nome) ou fecha (o foco, que
  // estava no cartão e se perdeu com ele, volta ao pino da loja ou ao mapa). Um efeito normal e não de
  // `layout`: corre depois dos do MapaLojas (os filhos primeiro), por isso o pino de uma loja que acabou de
  // entrar na rota já saiu do mapa e não recebe o foco.
  const idDoCartao = vista.lojaEscolhida?.id ?? null;
  const cartaoAntes = useRef(null);
  useEffect(() => {
    const antes = cartaoAntes.current;
    cartaoAntes.current = idDoCartao;
    if (idDoCartao === antes) return;
    // O cartão é sempre o do último pino tocado (só o `escolherLoja` desta página o abre).
    if (idDoCartao !== null) {
      mapa?.centrarEm(tocada.current?.loja);
      tituloDoCartao.current?.focus({ preventScroll: true });
      return;
    }
    if (document.activeElement !== document.body) return;
    const pino = tocada.current?.marcador?.element;
    if (pino?.isConnected) pino.focus();
    else mapa?.focar();
  }, [idDoCartao, mapa]);

  const p = planeador;

  // O toque num pino de uma loja esbatida (o cartão) e o toque no mapa (o ponto, ou fecha o cartão).
  const escolherLoja = (loja, marcador) => {
    tocada.current = { loja, marcador };
    p?.escolherLoja(loja);
  };
  const tocarNoMapa = (ponto) => p?.tocarNoMapa(ponto);

  // O Escape no planeador cancela o "Ponto no mapa" ou fecha o cartão. Os diálogos e os menus do Radix (a
  // pergunta do "Guardar rota", o motivo) tratam o Escape deles primeiro e marcam-no (`defaultPrevented`), e a
  // pega da lista também, a meio de um movimento.
  function aoCarregarNumaTecla(evento) {
    if (evento.key !== 'Escape' || evento.defaultPrevented) return;
    if (vista.escolherPonto !== null) p?.escolherPonto(null);
    else if (vista.lojaEscolhida !== null) p?.escolherLoja(null);
  }

  if (vista.estado !== 'rota') {
    return (
      <div className={cheio ? 'h-full overflow-y-auto p-4 md:p-6 lg:p-8' : undefined} data-testid="crm-rota">
        {vista.estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR} />}
        {vista.estado === 'falha' && (
          <Mensagem titulo={vista.titulo} mensagem={vista.falha.mensagem} caminhoRotas={vista.caminhoRotas}>
            <Button
              type="button"
              className="h-11"
              onClick={() => p?.tentarDeNovo()}
              disabled={vista.falha.aTentar}
              data-testid="crm-rota-tentar"
            >
              {TEXTO_TENTAR_DE_NOVO}
            </Button>
          </Mensagem>
        )}
        {vista.estado === 'data_invalida' && (
          <Mensagem titulo={vista.titulo} mensagem={vista.falha.mensagem} caminhoRotas={vista.caminhoRotas} />
        )}
      </div>
    );
  }

  const estadoDoMapa = configuracaoDoMapa(vista.configuracao);
  const mensagemDoMapa = mensagemSemMapa({ estado: estadoDoMapa, falhou: mapaFalhou });
  const comMapa = mensagemDoMapa === null && estadoDoMapa === 'ok';
  const desligada = vista.semRede || vista.conflito !== null;
  const faixa = faixaDoPonto(vista.escolherPonto);

  return (
    // O Escape sobe dos filhos (o painel, o cartão) até aqui; o planeador em si não recebe o foco.
    <div className="crm-planeador" onKeyDown={aoCarregarNumaTecla} data-testid="crm-rota">
      <aside ref={painel} className="crm-planeador__painel" aria-label={TITULO_PAINEL}>
        <div className="grid gap-4 p-4">
          <header className="grid gap-1">
            <Link
              to={vista.caminhoRotas}
              className="inline-flex min-h-11 w-fit items-center gap-1 rounded-md text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="crm-rota-rotas"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              {TEXTO_ROTAS}
            </Link>
            <h1 className="font-heading text-xl font-bold leading-tight">{vista.titulo}</h1>
          </header>

          {vista.textoLeitura && (
            <p role="status" className="rounded-xl border bg-muted px-3 py-2 text-sm font-medium" data-testid="crm-rota-leitura">
              {vista.textoLeitura}
            </p>
          )}

          {vista.conflito && (
            <div role="alert" className="grid gap-2 rounded-xl border border-destructive/40 bg-destructive/5 p-3" data-testid="crm-rota-conflito">
              <p className="text-sm font-semibold text-destructive">{vista.conflito.mensagem}</p>
              {vista.conflito.erro && <p className="text-sm text-destructive">{vista.conflito.erro}</p>}
              <Button
                type="button"
                variant="outline"
                className="h-11 w-fit"
                onClick={() => p?.recarregar()}
                disabled={vista.conflito.aRecarregar}
                data-testid="crm-rota-recarregar"
              >
                {vista.conflito.aRecarregar ? TEXTO_A_RECARREGAR : TEXTO_RECARREGAR}
              </Button>
            </div>
          )}

          {vista.alerta && (
            <p role="alert" className="rounded-xl border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive" data-testid="crm-rota-alerta">
              {vista.alerta.mensagem}
            </p>
          )}

          <ResumoRota
            vista={vista}
            aoCalcular={() => p?.calcularMelhorOrdem()}
            aoRecalcular={() => p?.recalcularHoras()}
            aoGuardar={() => p?.guardar()}
            aoResponderGuardar={(sim) => p?.responderGuardar(sim)}
          />

          <DefinicoesDoDia
            definicoes={vista.definicoes}
            escolherPonto={vista.escolherPonto}
            somenteLeitura={vista.somenteLeitura}
            aoMudarDefinicao={(chave, valor) => p?.mudarDefinicao(chave, valor)}
            aoUsarFabrica={(ponta) => p?.usarFabrica(ponta)}
            aoEscolherPonto={(ponta) => p?.escolherPonto(ponta)}
          />

          {seccoesDoPainel(vista.seccoes).map((seccao) => (
            <ListaParagens
              key={seccao.chave}
              titulo={seccao.titulo}
              linhas={seccao.linhas}
              arrastavel={seccao.arrastavel}
              somenteLeitura={vista.somenteLeitura}
              desligada={desligada}
              evitarPortagens={vista.definicoes?.evitar_portagens === true}
              aoMover={(de, para) => p?.mover(de, para)}
              aoSubir={(id) => p?.subir(id)}
              aoDescer={(id) => p?.descer(id)}
              aoRetirar={(id) => p?.retirar(id)}
              aoMudarMotivo={(id, motivo) => p?.mudarMotivo(id, motivo)}
              aoMudarTempo={(id, minutos) => p?.mudarTempo(id, minutos)}
              aoManter={seccao.comManter ? (id) => p?.manter(id) : undefined}
              aoPorNaRota={seccao.comPorNaRota ? (id) => p?.porNaRota(id) : undefined}
            />
          ))}

          <SugestoesRota
            sugestoes={vista.sugestoes}
            podeAdicionar={vista.podeAdicionar}
            aoAdicionar={(lojaId) => p?.adicionar(lojaId)}
            aoTentarDeNovo={() => p?.tentarDeNovo()}
          />
        </div>
        <RodapeOrs atribuicao={vista.atribuicaoOrs} />
      </aside>

      <div ref={areaDoMapa} className="crm-planeador__mapa">
        <div className="flex h-full flex-col">
          {vista.falhaDoMapa && (
            <div role="alert" className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-4 py-2.5" data-testid="crm-rota-falha-mapa">
              <p className="min-w-0 flex-1 text-sm font-medium text-destructive">{vista.falhaDoMapa.mensagem}</p>
              <Button
                type="button"
                variant="outline"
                className="h-11"
                onClick={() => p?.tentarDeNovo()}
                disabled={vista.falhaDoMapa.aTentar}
                data-testid="crm-rota-tentar-mapa"
              >
                {TEXTO_TENTAR_DE_NOVO}
              </Button>
            </div>
          )}
          {faixa && (
            <div role="status" className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-4 py-2" data-testid="crm-rota-faixa-ponto">
              <p className="flex min-w-0 flex-1 items-center gap-2 text-sm font-semibold">
                <Crosshair className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                {faixa.texto}
              </p>
              <Button
                type="button"
                variant="outline"
                className="h-11"
                onClick={() => p?.escolherPonto(null)}
                data-testid="crm-rota-faixa-cancelar"
              >
                {TEXTO_CANCELAR}
              </Button>
            </div>
          )}
          <div className="crm-mapa__vista bg-muted">
            {comMapa && (
              <MapaLojas
                classe="crm-mapa--planeador"
                negociosClicaveis={false}
                configuracao={vista.configuracao}
                lojas={vista.mapa.lojasForaDaRota}
                rota={vista.mapa}
                aoPronto={setMapa}
                aoFalhar={() => setMapaFalhou(true)}
                aoEscolherParagem={escolherParagem}
                aoEscolherLoja={escolherLoja}
                aoTocarNoMapa={tocarNoMapa}
              />
            )}
            {mensagemDoMapa && (
              <p role="status" className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground" data-testid="crm-rota-sem-mapa">
                {mensagemDoMapa}
              </p>
            )}
          </div>
          {/* O cartão vive fora da vista do mapa, por baixo dela: o mapa encolhe, nada o tapa. */}
          <CartaoLojaEscolhida
            loja={vista.lojaEscolhida}
            aoAdicionar={(lojaId, motivo) => p?.adicionar(lojaId, motivo)}
            aoFechar={() => p?.escolherLoja(null)}
            refTitulo={tituloDoCartao}
          />
        </div>
      </div>
    </div>
  );
}

export default function CrmRota() {
  const { data } = useParams();
  const { pathname } = useLocation();
  const base = baseCrm(pathname);
  const cheio = ecraCheioDoCrm(pathname);
  return <PlaneadorDoDia key={`${base} ${data}`} data={data} base={base} cheio={cheio} />;
}
