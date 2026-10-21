// Nova loja (desenho original §6.2; plano T2.27). Porta do ecrã
// public/assets/js/ecras/loja-nova.js do CRM autónomo, no aspeto do portal.
//
// Primeiro a localização (o `SeletorLocalizacao`: tocar no mapa, pesquisar a
// morada ou o lugar na Google, tocar num negócio do mapa ou "Estou nesta
// loja", e confirmar), depois os dados da loja (o
// `FormularioLoja`) e Guardar. As regras estão em `lib/crm/lojaNova.js` (com
// testes): esta página cria o ecrã num `useEffect`, desenha a `vista` que ele
// entrega e passa-lhe o que a pessoa faz.
//  - Guardar só fica ativo com o nome e a localização confirmada; sem rede,
//    "Guardar — sem rede" (`criarEstadoRede(window, navigator)`).
//  - Um 422 mostra os erros junto aos campos (o foco vai para o primeiro) e, se
//    for da localização, no seletor, com o pino outra vez por confirmar.
//  - Um 409 duplicado abre o `DialogoDuplicado`: "Sim, abrir X" abre a ficha
//    dessa loja, "Não, é outra loja" volta a enviar com `confirmar_duplicado`.
//  - Depois de gravar, o mapa da mesma casa centrado na loja nova, com o aviso
//    "Loja guardada" no `state` (o toast é do mapa, sem um daqui).
//  - Vinda de "Adicionar como loja" no mapa (plano do mapa Google, G16), a
//    página traz no `state` só o negócio ({negocio: {id, lat, lng}}, lido uma
//    vez com `negocioDoEstado`). Quando o seletor tem mapa (`aoPronto`), o
//    pino vai para esse negócio (`usarNegocio`, com o ponto tocado de reserva
//    se a Google falhar) e o `state` sai do histórico (recarregar a página não
//    o repete). O pino fica por arrastar até à porta da loja (o
//    Confirmar só depois disso) e o nome escreve-se à mão, com a dica por
//    baixo do campo "Nome" (`vista.dicaNome`) desde a chegada
//    (`comNegocio`; revisão do mapa Google, MAPA-G-3). Sem mapa, nada se pede.
// A configuração do mapa pede-se uma vez (`obterConfigMapa`): `undefined`
// enquanto chega, `null` se falhar (o seletor diz que não há mapa) e sempre o
// mesmo objeto entre desenhos (um objeto novo criava outro mapa).
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Loader2, MapPinPlus, Save, WifiOff } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { Button } from '../../components/ui/button';
import DialogoDuplicado from '../../components/crm/DialogoDuplicado';
import FormularioLoja from '../../components/crm/FormularioLoja';
import SeletorLocalizacao from '../../components/crm/SeletorLocalizacao';
import { baseCrm } from '../../lib/crm/acesso';
import { criarLoja, listarRegioes, obterConfigMapa } from '../../lib/crm/api';
import {
  TEXTO_A_GUARDAR, TEXTO_GUARDAR_SEM_REDE, criarLojaNova, negocioDoEstado,
} from '../../lib/crm/lojaNova';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  listarRegioes: () => listarRegioes(),
  criarLoja: (corpo) => criarLoja(corpo),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

// O localStorage pode não existir ou lançar (browser bloqueado, modo privado): a loja grava-se na mesma, só
// não fica lembrada a região (o lojaNova.js também apanha os erros de leitura e escrita).
function armazenamento() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export default function CrmLojaNova() {
  const { pathname, state } = useLocation();
  const navigate = useNavigate();
  const base = baseCrm(pathname);
  const idDados = useId();
  const seletor = useRef(null);
  const formulario = useRef(null);
  const botaoGuardar = useRef(null);
  const [configuracao, setConfiguracao] = useState(undefined);
  const [ecra, setEcra] = useState(null);
  // O negócio com que a página abriu ("Adicionar como loja" no mapa), lido uma vez; usa-se uma só vez.
  const [negocio] = useState(() => negocioDoEstado(state));
  const negocioUsado = useRef(false);
  const comNegocio = negocio !== null;
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarLojaNova({ storage: armazenamento(), rede: REDE, comNegocio }).vista);
  // O campo que deve receber o foco quando o ecrã já o mostrar (o primeiro com erro de um 422).
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);

  const navegar = useRef(navigate);
  useLayoutEffect(() => {
    navegar.current = navigate;
  });

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
    const criado = criarLojaNova({
      api: API,
      storage: armazenamento(),
      rede: REDE,
      base,
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
      aoFocar: (campo) => {
        if (!ativo) return;
        focoPendente.current = campo;
        setPedidosDeFoco((n) => n + 1);
      },
      comNegocio,
    });
    setEcra(criado);
    setVista(criado.vista);
    criado.iniciar();
    return () => {
      ativo = false;
      criado.destruir();
    };
  }, [base, comNegocio]);

  // O foco pedido pelo ecrã, depois de o React mostrar o erro do campo.
  useLayoutEffect(() => {
    const campo = focoPendente.current;
    if (!campo) return;
    focoPendente.current = null;
    formulario.current?.focar(campo);
  }, [pedidosDeFoco, vista]);

  // O seletor tem mapa (e a `ref` já o usa): o pino vai para o negócio com que a página abriu, e o `state`
  // sai do histórico. Uma só vez, também com o StrictMode ou um seletor novo.
  const aoPronto = (pronto) => {
    if (!pronto || negocio === null || negocioUsado.current) return;
    negocioUsado.current = true;
    seletor.current?.usarNegocio(negocio.id, { reserva: { lat: negocio.lat, lng: negocio.lng } });
    navigate({ pathname }, { replace: true, state: null });
  };

  const { guardar } = vista;
  let iconeGuardar = <Save aria-hidden="true" />;
  if (guardar.texto === TEXTO_A_GUARDAR) iconeGuardar = <Loader2 className="animate-spin" aria-hidden="true" />;
  else if (guardar.texto === TEXTO_GUARDAR_SEM_REDE) iconeGuardar = <WifiOff aria-hidden="true" />;

  return (
    <div className="mx-auto max-w-3xl space-y-6 animate-fade-in" data-testid="crm-loja-nova">
      <PageHeader icon={MapPinPlus} title="Nova loja" subtitle="CRM Purple House" />

      <div className="rounded-2xl border bg-card p-4 md:p-6">
        <SeletorLocalizacao
          ref={seletor}
          configuracao={configuracao}
          comGps
          aoMudar={(localizacao) => ecra?.mudarLocalizacao(localizacao)}
          aoEscolherMorada={(sugestao) => ecra?.escolherMorada(sugestao)}
          aoSugerirMorada={(sugestao) => ecra?.sugerirMorada(sugestao)}
          aoPronto={aoPronto}
        />
      </div>

      {/* noValidate: as mensagens dos campos são as do servidor (pt-PT), não as do browser. */}
      <form
        noValidate
        aria-labelledby={idDados}
        className="space-y-5 rounded-2xl border bg-card p-4 md:p-6"
        onSubmit={(evento) => {
          evento.preventDefault();
          ecra?.guardar();
        }}
        data-testid="crm-loja-nova-formulario"
      >
        <h2 id={idDados} className="font-heading text-lg font-semibold">Dados da loja</h2>
        <FormularioLoja
          ref={formulario}
          valores={vista.valores}
          erros={vista.erros}
          opcoesRegiao={vista.opcoesRegiao}
          valorRegiao={vista.valorRegiao}
          dicas={{ nome: vista.dicaNome }}
          aoMudar={(campo, valor) => ecra?.mudarCampo(campo, valor)}
        />
        <div className="space-y-2">
          {vista.alerta && (
            <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-loja-nova-alerta">
              {vista.alerta}
            </p>
          )}
          {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
          <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="crm-loja-nova-falta">
            {guardar.falta ?? ''}
          </p>
          <Button
            ref={botaoGuardar}
            type="submit"
            className="h-11 w-full"
            disabled={!guardar.ativo}
            data-testid="crm-loja-nova-guardar"
          >
            {iconeGuardar}
            {guardar.texto}
          </Button>
        </div>
      </form>

      <DialogoDuplicado
        duplicado={vista.duplicado}
        aoResponder={(valor) => ecra?.responder(valor)}
        refFocoAoFechar={botaoGuardar}
      />
    </div>
  );
}
