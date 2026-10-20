// Ficha da loja, em `lojas/:lojaId` (desenho original §6.3; plano T2.28).
// Porta do ecrã public/assets/js/ecras/loja.js do CRM autónomo, no aspeto do
// portal.
//
// O formulário da nova loja já preenchido, com o horário de receção e os dias
// fechada; a fase num toque; "Corrigir localização" com o seletor; a faixa do
// conflito; Apagar com confirmação. As regras estão em `lib/crm/ficha.js` (com
// testes): esta página cria o ecrã num `useEffect`, desenha a `vista` que ele
// entrega e passa-lhe o que a pessoa faz.
//  - Tocar numa pastilha da fase grava logo (só a fase); "Fase guardada" e
//    "Alterações guardadas" são toasts do sonner.
//  - Guardar envia só o que mudou + o `atualizado_em`; sem rede, "Guardar — sem
//    rede" (`criarEstadoRede(window, navigator)`); o porquê de estar
//    desativado fica por baixo dele.
//  - 409 conflito → a faixa "Alterado por outra pessoa — recarregar", com o
//    foco no Recarregar.
//  - "Corrigir localização" monta o `SeletorLocalizacao` (o mapa Google, com a
//    pesquisa da Google, o negócio selecionado e "Estou nesta loja") com o
//    pino no sítio guardado, com a origem e o `google_place_id` da loja (a
//    `key` muda a cada abertura: o `inicial` só se lê ao criar), e um 409
//    duplicado abre o `DialogoDuplicado`.
//  - Apagar pergunta num `AlertDialog` (o foco na escolha que não apaga) e,
//    apagada, volta ao mapa da mesma casa com o aviso "Loja apagada" (o toast é
//    do mapa).
// Outra loja na mesma rota (ex.: "Sim, abrir X") é outra ficha: a `key` do
// `lojaId` cria tudo de novo. Os dados da loja entram como texto (o React
// escapa-os).
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import {
  Loader2, MapPin, MapPinned, RefreshCw, Save, Store, Trash2, TriangleAlert, WifiOff,
} from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { Button } from '../../components/ui/button';
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import DialogoDuplicado from '../../components/crm/DialogoDuplicado';
import FormularioLoja from '../../components/crm/FormularioLoja';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import SeletorLocalizacao from '../../components/crm/SeletorLocalizacao';
import { baseCrm } from '../../lib/crm/acesso';
import {
  alterarLoja, apagarLoja, listarRegioes, obterConfigMapa, obterLoja,
} from '../../lib/crm/api';
import {
  TEXTO_A_CARREGAR, TEXTO_CANCELAR_CORRECAO, TEXTO_CONFLITO, TEXTO_CORRIGIR, TEXTO_RECARREGAR, caminhoNoMapa,
  criarFicha,
} from '../../lib/crm/ficha';
import { TEXTO_A_GUARDAR, TEXTO_GUARDAR_SEM_REDE } from '../../lib/crm/lojaNova';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  obterLoja: (id) => obterLoja(id),
  listarRegioes: () => listarRegioes(),
  alterarLoja: (id, corpo) => alterarLoja(id, corpo),
  apagarLoja: (id) => apagarLoja(id),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const VARIANTES_APAGAR = Object.freeze({ normal: 'outline', perigo: 'destructive' });

export default function CrmLoja() {
  const { lojaId = '' } = useParams();
  return <FichaDaLoja key={lojaId} id={lojaId} />;
}

function FichaDaLoja({ id }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const base = baseCrm(pathname);
  const idDados = useId();
  const idLocalizacao = useId();
  const seletor = useRef(null);
  const formulario = useRef(null);
  const botaoGuardar = useRef(null);
  const botaoRecarregar = useRef(null);
  const botaoCorrigir = useRef(null);
  const botaoApagar = useRef(null);
  const primeiraEscolhaApagar = useRef(null);
  const [configuracao, setConfiguracao] = useState(undefined);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarFicha({ rede: REDE, base, id }).vista);
  // O que deve receber o foco quando o ecrã já o mostrar (o Recarregar, o "Corrigir localização", ou o
  // primeiro campo com erro de um 422).
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

  const navegar = useRef(navigate);
  useLayoutEffect(() => {
    navegar.current = navigate;
  });

  // A configuração do mapa (para o seletor), uma vez: undefined enquanto chega, null se falhar.
  useEffect(() => {
    let ativo = true;
    obterConfigMapa().then(
      (dados) => {
        if (ativo) setConfiguracao(dados ?? null);
      },
      () => {
        if (ativo) setConfiguracao(null);
      },
    );
    return () => {
      ativo = false;
    };
  }, []);

  useEffect(() => {
    let ativo = true;
    const criado = criarFicha({
      api: API,
      rede: REDE,
      base,
      id,
      navegar: (caminho, opcoes) => navegar.current(caminho, opcoes),
      seletor: {
        limparErro: () => seletor.current?.limparErro(),
        desconfirmar: () => seletor.current?.desconfirmar(),
        mostrarErro: (texto) => seletor.current?.mostrarErro(texto),
        focar: () => seletor.current?.focar(),
      },
      aoMudarVista: (nova) => {
        if (ativo) setVista(nova);
      },
      aoFocar: (alvo) => {
        if (!ativo) return;
        focoPendente.current = alvo;
        setPedidosDeFoco((n) => n + 1);
      },
      aoAvisar: (texto) => {
        if (ativo) toast.success(texto);
      },
    });
    setEcra(criado);
    setVista(criado.vista);
    criado.iniciar();
    return () => {
      ativo = false;
      criado.destruir();
    };
  }, [base, id]);

  // O foco pedido pelo ecrã, depois de o React mostrar o que vai recebê-lo.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    if (alvo === 'recarregar') botaoRecarregar.current?.focus();
    else if (alvo === 'corrigir') botaoCorrigir.current?.focus();
    else formulario.current?.focar(alvo);
  }, [pedidosDeFoco, vista]);

  const { guardar, conflito, correcao, apagar } = vista;
  let iconeGuardar = <Save aria-hidden="true" />;
  if (guardar.texto === TEXTO_A_GUARDAR) iconeGuardar = <Loader2 className="animate-spin" aria-hidden="true" />;
  else if (guardar.texto === TEXTO_GUARDAR_SEM_REDE) iconeGuardar = <WifiOff aria-hidden="true" />;

  return (
    <div className="mx-auto max-w-3xl space-y-6 animate-fade-in" data-testid="crm-ficha">
      <PageHeader icon={Store} title={<span className="[overflow-wrap:anywhere]">{vista.titulo}</span>} subtitle="Ficha da loja · CRM Purple House">
        {vista.estado === 'ficha' && (
          <Button asChild variant="outline" className="h-11">
            <Link to={caminhoNoMapa(base, id)} data-testid="crm-ficha-ver-no-mapa">
              <MapPinned aria-hidden="true" />
              Ver no mapa
            </Link>
          </Button>
        )}
      </PageHeader>

      {vista.estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR} />}

      {vista.estado === 'falha' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
          <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-ficha-falha">
            {vista.falha.mensagem}
          </p>
          {vista.falha.tentar && (
            <Button type="button" className="h-11" onClick={() => ecra?.tentarDeNovo()} disabled={vista.falha.aTentar}>
              Tentar novamente
            </Button>
          )}
          {vista.falha.voltar && (
            <Button asChild variant="outline" className="h-11">
              <Link to={`${base}/mapa`}>Voltar ao mapa</Link>
            </Button>
          )}
        </div>
      )}

      {vista.estado === 'ficha' && (
        <>
          {conflito && (
            <div
              role="alert"
              className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border border-warning bg-warning/10 p-4"
              data-testid="crm-ficha-conflito"
            >
              <TriangleAlert className="h-5 w-5 shrink-0 text-warning-strong" aria-hidden="true" />
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-semibold text-warning-strong">{TEXTO_CONFLITO}</p>
                {conflito.erro && <p className="text-sm font-medium text-destructive">{conflito.erro}</p>}
              </div>
              <Button
                ref={botaoRecarregar}
                type="button"
                variant="outline"
                className="h-11"
                onClick={() => ecra?.recarregar()}
                disabled={conflito.aRecarregar}
              >
                <RefreshCw className={conflito.aRecarregar ? 'animate-spin' : undefined} aria-hidden="true" />
                {TEXTO_RECARREGAR}
              </Button>
            </div>
          )}

          {/* noValidate: as mensagens dos campos são as do servidor (pt-PT), não as do browser. */}
          <form
            noValidate
            aria-labelledby={idDados}
            className="space-y-5 rounded-2xl border bg-card p-4 md:p-6"
            onSubmit={(evento) => {
              evento.preventDefault();
              ecra?.guardar();
            }}
            data-testid="crm-ficha-formulario"
          >
            <h2 id={idDados} className="font-heading text-lg font-semibold">Dados da loja</h2>
            {/* Enquanto grava, os campos e a localização ficam desativados (a resposta volta a preenchê-los). */}
            <fieldset disabled={vista.camposDesativados} className="m-0 min-w-0 space-y-6 border-0 p-0">
              <FormularioLoja
                ref={formulario}
                ficha
                valores={vista.valores}
                erros={vista.erros}
                opcoesRegiao={vista.opcoesRegiao}
                valorRegiao={vista.valorRegiao}
                desativado={vista.camposDesativados}
                aoMudar={(campo, valor) => ecra?.mudarCampo(campo, valor)}
                aoMudarFase={() => ecra?.guardarFase()}
                aoAlternarDia={(dia, marcado) => ecra?.alternarDia(dia, marcado)}
              />

              <div className="space-y-3 border-t pt-5" data-testid="crm-ficha-localizacao">
                {correcao ? (
                  <>
                    <SeletorLocalizacao
                      key={correcao.chave}
                      ref={seletor}
                      configuracao={configuracao}
                      inicial={correcao.inicial}
                      comGps
                      focarAoIniciar
                      aoMudar={(localizacao) => ecra?.mudarLocalizacao(localizacao)}
                      aoEscolherMorada={(sugestao) => ecra?.escolherMorada(sugestao)}
                      aoSugerirMorada={(sugestao) => ecra?.sugerirMorada(sugestao)}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-11 w-full sm:w-auto"
                      onClick={() => ecra?.cancelarCorrecao()}
                      data-testid="crm-ficha-cancelar-correcao"
                    >
                      {TEXTO_CANCELAR_CORRECAO}
                    </Button>
                  </>
                ) : (
                  <section aria-labelledby={idLocalizacao} className="space-y-3">
                    <h2 id={idLocalizacao} className="font-heading text-lg font-semibold">Localização</h2>
                    <p className="text-sm text-muted-foreground" data-testid="crm-ficha-resumo">{vista.resumoLocalizacao}</p>
                    <Button
                      ref={botaoCorrigir}
                      type="button"
                      variant="outline"
                      className="h-11 w-full sm:w-auto"
                      onClick={() => ecra?.abrirCorrecao()}
                      data-testid="crm-ficha-corrigir"
                    >
                      <MapPin aria-hidden="true" />
                      {TEXTO_CORRIGIR}
                    </Button>
                  </section>
                )}
              </div>
            </fieldset>

            <div className="space-y-2 border-t pt-5">
              {vista.alerta && (
                <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-ficha-alerta">
                  {vista.alerta}
                </p>
              )}
              {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
              <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="crm-ficha-falta">
                {guardar.falta ?? ''}
              </p>
              <Button
                ref={botaoGuardar}
                type="submit"
                className="h-11 w-full"
                disabled={!guardar.ativo}
                data-testid="crm-ficha-guardar"
              >
                {iconeGuardar}
                {guardar.texto}
              </Button>
            </div>
          </form>

          <div className="space-y-2 rounded-2xl border bg-card p-4 md:p-6">
            {apagar.erro && (
              <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-ficha-erro-apagar">
                {apagar.erro}
              </p>
            )}
            <Button
              ref={botaoApagar}
              type="button"
              variant="outline"
              className="h-11 w-full border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive sm:w-auto"
              onClick={() => ecra?.pedirApagar()}
              disabled={!apagar.ativo}
              data-testid="crm-ficha-apagar"
            >
              {apagar.ativo ? <Trash2 aria-hidden="true" /> : <Loader2 className="animate-spin" aria-hidden="true" />}
              {apagar.texto}
            </Button>
          </div>

          <DialogoDuplicado
            duplicado={vista.duplicado}
            aoResponder={(valor) => ecra?.responderDuplicado(valor)}
            refFocoAoFechar={botaoGuardar}
          />

          <AlertDialog
            open={apagar.pergunta !== null}
            onOpenChange={(abrir) => {
              if (!abrir) ecra?.responderApagar(null);
            }}
          >
            {apagar.pergunta && (
              <AlertDialogContent
                className="w-[calc(100%-2rem)] max-w-[26rem] rounded-2xl"
                onOpenAutoFocus={(evento) => {
                  // O foco vai para a primeira escolha: a que não apaga.
                  evento.preventDefault();
                  primeiraEscolhaApagar.current?.focus();
                }}
                onCloseAutoFocus={(evento) => {
                  evento.preventDefault();
                  botaoApagar.current?.focus();
                }}
                data-testid="crm-dialogo-apagar"
              >
                <AlertDialogTitle className="text-base font-semibold">{apagar.pergunta.pergunta}</AlertDialogTitle>
                <AlertDialogDescription className="text-base text-foreground">{apagar.pergunta.aviso}</AlertDialogDescription>
                <div className="flex flex-col gap-2">
                  {apagar.pergunta.botoes.map((botao, i) => (
                    <Button
                      key={botao.valor ?? 'cancelar'}
                      ref={i === 0 ? primeiraEscolhaApagar : undefined}
                      type="button"
                      variant={VARIANTES_APAGAR[botao.variante] ?? 'outline'}
                      className="h-auto min-h-11 w-full whitespace-normal py-2"
                      onClick={() => ecra?.responderApagar(botao.valor)}
                    >
                      {botao.texto}
                    </Button>
                  ))}
                </div>
              </AlertDialogContent>
            )}
          </AlertDialog>
        </>
      )}
    </div>
  );
}
