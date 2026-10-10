// Definições › Fábrica (plano T2.30; desenho original §6.7): a morada da
// fábrica e o ponto no mapa. Porta do componente
// public/assets/js/componentes/definicoes-fabrica.js do CRM autónomo, no
// aspeto do portal. O `CrmDefinicoes` carrega esta página à parte
// (`React.lazy`), só quando se abre o separador: é a única das Definições com
// o mapa (o Leaflet).
//
// As regras estão em `lib/crm/fabrica.js` (com testes): esta página cria o
// ecrã num `useEffect`, desenha a `vista` que ele entrega e passa-lhe o que a
// pessoa faz.
//  - "Mudar o ponto no mapa" monta o `SeletorLocalizacao` sem GPS, com os
//    textos da fábrica e o pino solto no ponto atual (a `key` muda a cada
//    abertura: o `inicial` só se lê ao criar). O botão em que se tocou
//    desaparece: o foco vai para "Confirmar localização" (`focarAoIniciar`),
//    ou, sem mapa, para "Cancelar a mudança do ponto".
//  - A configuração do mapa pede-se uma vez (`obterConfigMapa`): `undefined`
//    enquanto chega, `null` se falhar (o seletor diz que o mapa não está
//    disponível; a morada guarda-se na mesma).
//  - Enquanto grava, a morada e o ponto ficam desativados (`fieldset`); o
//    porquê de Guardar estar desativado fica por baixo dele; "Dados da fábrica
//    guardados." é um toast do sonner.
// Os dados entram como texto (o React escapa-os).
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, MapPin, Save } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
// O `crm.css` antes do seletor (que traz o `leaflet.css`), pela mesma ordem das outras páginas do CRM (o
// formulário e o cartão trazem-no primeiro). Sem isto, o build avisava "Conflicting order" entre os dois.
import '../../components/crm/crm.css';
import SeletorLocalizacao from '../../components/crm/SeletorLocalizacao';
import { alterarDefinicoes, obterConfigMapa, obterDefinicoes } from '../../lib/crm/api';
import {
  MORADA_MAXIMO_FABRICA,
  TEXTOS_SELETOR_FABRICA,
  TEXTO_A_CARREGAR_FABRICA,
  TEXTO_A_GUARDAR,
  TEXTO_AJUDA_PONTO,
  TEXTO_CANCELAR_MUDANCA,
  TEXTO_DESCRICAO_FABRICA,
  TEXTO_MORADA_FABRICA,
  TEXTO_MUDAR_PONTO,
  TEXTO_PONTO_NO_MAPA,
  TITULO_FABRICA,
  criarFabrica,
} from '../../lib/crm/fabrica';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  obterDefinicoes: () => obterDefinicoes(),
  alterarDefinicoes: (corpo) => alterarDefinicoes(corpo),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const CLASSE_INVALIDO = 'aria-[invalid=true]:border-destructive';

export default function DefinicoesFabrica() {
  const idTitulo = useId();
  const idMorada = useId();
  const idErroMorada = `${idMorada}-erro`;
  const idPonto = useId();
  const seletor = useRef(null);
  const campoMorada = useRef(null);
  const botaoMudar = useRef(null);
  const botaoCancelar = useRef(null);
  const [configuracao, setConfiguracao] = useState(undefined);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarFabrica({ rede: REDE }).vista);
  // O que deve receber o foco quando o ecrã já o mostrar (a morada com erro, ou "Mudar o ponto no mapa").
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

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
    const criado = criarFabrica({
      api: API,
      rede: REDE,
      seletor: {
        limparErro: () => seletor.current?.limparErro(),
        desconfirmar: () => seletor.current?.desconfirmar(),
        mostrarErro: (texto) => seletor.current?.mostrarErro(texto),
        focar: () => seletor.current?.focar(),
      },
      aoMudarVista: (nova) => {
        if (ativo) setVista(nova);
      },
      aoAvisar: (texto) => {
        if (ativo) toast.success(texto);
      },
      aoFocar: (alvo) => {
        if (!ativo) return;
        focoPendente.current = alvo;
        setPedidosDeFoco((n) => n + 1);
      },
    });
    setEcra(criado);
    setVista(criado.vista);
    criado.iniciar();
    return () => {
      ativo = false;
      criado.destruir();
    };
  }, []);

  // O foco pedido pelo ecrã, depois de o React mostrar o que vai recebê-lo.
  useLayoutEffect(() => {
    const alvo = focoPendente.current;
    if (!alvo) return;
    focoPendente.current = null;
    if (alvo === 'morada') campoMorada.current?.focus();
    else if (alvo === 'mudar') botaoMudar.current?.focus();
  }, [pedidosDeFoco, vista]);

  // Sem mapa, o seletor não tem "Confirmar localização" que receba o foco: vai para o Cancelar, ao lado.
  const chaveCorrecao = vista.correcao?.chave ?? null;
  useLayoutEffect(() => {
    if (chaveCorrecao !== null && configuracao === null) botaoCancelar.current?.focus();
  }, [chaveCorrecao, configuracao]);

  const {
    estado, falha, correcao, guardar,
  } = vista;

  return (
    <section aria-labelledby={idTitulo} className="space-y-4" data-testid="crm-fabrica">
      <div className="space-y-1">
        <h2 id={idTitulo} className="font-heading text-lg font-semibold">{TITULO_FABRICA}</h2>
        <p className="text-sm text-muted-foreground">{TEXTO_DESCRICAO_FABRICA}</p>
      </div>

      {estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR_FABRICA} />}

      {estado === 'falha' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
          <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-fabrica-falha">
            {falha.mensagem}
          </p>
          <Button type="button" className="h-11" onClick={() => ecra?.tentarDeNovo()} disabled={falha.aTentar}>
            Tentar novamente
          </Button>
        </div>
      )}

      {estado === 'pronto' && (
        // noValidate: as mensagens dos campos são as do servidor (pt-PT), não as do browser.
        <form
          noValidate
          aria-labelledby={idTitulo}
          className="space-y-5 rounded-2xl border bg-card p-4 md:p-6"
          onSubmit={(evento) => {
            evento.preventDefault();
            ecra?.guardar();
          }}
          data-testid="crm-fabrica-formulario"
        >
          {/* Enquanto grava, a morada e o ponto ficam desativados (a resposta volta a preenchê-los). */}
          <fieldset disabled={vista.camposDesativados} className="m-0 min-w-0 space-y-5 border-0 p-0">
            <div className="space-y-1.5">
              <Label htmlFor={idMorada}>{TEXTO_MORADA_FABRICA}</Label>
              <Input
                id={idMorada}
                ref={campoMorada}
                value={vista.morada}
                onChange={(evento) => ecra?.mudarMorada(evento.target.value)}
                maxLength={MORADA_MAXIMO_FABRICA}
                autoComplete="off"
                className={`h-11 ${CLASSE_INVALIDO}`}
                aria-invalid={vista.erroMorada ? 'true' : undefined}
                aria-describedby={vista.erroMorada ? idErroMorada : undefined}
                data-testid="crm-fabrica-morada"
              />
              {vista.erroMorada && (
                <p id={idErroMorada} className="text-sm font-medium text-destructive">{vista.erroMorada}</p>
              )}
            </div>

            <div className="space-y-3 border-t pt-5" data-testid="crm-fabrica-ponto">
              {correcao ? (
                <>
                  <SeletorLocalizacao
                    key={correcao.chave}
                    ref={seletor}
                    configuracao={configuracao}
                    inicial={correcao.inicial}
                    textos={TEXTOS_SELETOR_FABRICA}
                    focarAoIniciar
                    aoMudar={(ponto) => ecra?.mudarPonto(ponto)}
                    aoEscolherMorada={(sugestao) => ecra?.escolherMorada(sugestao)}
                  />
                  <Button
                    ref={botaoCancelar}
                    type="button"
                    variant="ghost"
                    className="h-11 w-full sm:w-auto"
                    onClick={() => ecra?.cancelarCorrecao()}
                    data-testid="crm-fabrica-cancelar-ponto"
                  >
                    {TEXTO_CANCELAR_MUDANCA}
                  </Button>
                </>
              ) : (
                <section aria-labelledby={idPonto} className="space-y-2">
                  <h3 id={idPonto} className="font-heading text-base font-semibold">{TEXTO_PONTO_NO_MAPA}</h3>
                  <p className="text-sm tabular-nums" data-testid="crm-fabrica-resumo">{vista.resumoPonto}</p>
                  <p className="text-sm text-muted-foreground">{TEXTO_AJUDA_PONTO}</p>
                  {vista.erroPonto && (
                    <p role="alert" className="text-sm font-semibold text-destructive" data-testid="crm-fabrica-erro-ponto">
                      {vista.erroPonto}
                    </p>
                  )}
                  <Button
                    ref={botaoMudar}
                    type="button"
                    variant="outline"
                    className="h-11 w-full sm:w-auto"
                    onClick={() => ecra?.abrirCorrecao()}
                    data-testid="crm-fabrica-mudar-ponto"
                  >
                    <MapPin aria-hidden="true" />
                    {TEXTO_MUDAR_PONTO}
                  </Button>
                </section>
              )}
            </div>
          </fieldset>

          <div className="space-y-2 border-t pt-5">
            {vista.alerta && (
              <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-fabrica-alerta">
                {vista.alerta}
              </p>
            )}
            {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
            <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="crm-fabrica-falta">
              {guardar.falta ?? ''}
            </p>
            <Button type="submit" className="h-11 w-full" disabled={!guardar.ativo} data-testid="crm-fabrica-guardar">
              {guardar.texto === TEXTO_A_GUARDAR
                ? <Loader2 className="animate-spin" aria-hidden="true" />
                : <Save aria-hidden="true" />}
              {guardar.texto}
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
