// Definições › Rotas (plano F3 T3.41; §1 "Definições do CRM"): as horas com que nasce cada rota nova e o
// tempo de serviço de cada paragem nova, por motivo. Só o admin do CRM (o `CrmDefinicoes` está atrás do
// `SoAdminCrm`; a API recusa os outros com 403).
//
// As regras estão em `lib/crm/definicoesRotas.js` (com testes; T3.34): esta página cria o ecrã num
// `useEffect`, desenha a `vista` que ele entrega e passa-lhe o que a pessoa escreve (molde do
// `DefinicoesFabrica.js`, sem o mapa: não precisa de se carregar à parte).
//  - "Hora de saída" e "Hora limite de regresso" soltas (`<input type="time">`) e os quatro tempos num
//    `fieldset` com a legenda do grupo ("Tempo de serviço (min)") e a ajuda dos limites.
//  - O formulário é `noValidate`: quem valida é o servidor. O 422 fica junto de cada campo
//    (`aria-invalid`/`aria-describedby`), com o foco no primeiro (`aoFocar`); a coerência das horas vem no
//    regresso. "Definições das rotas guardadas." é um toast do sonner.
//  - Enquanto grava, os campos ficam desativados (`fieldset`). O Guardar fica com `aria-disabled` (e não
//    `disabled`), como os botões das Regiões: o foco fica nele. Se o foco se perdeu ao gravar (o Enter num
//    campo, que o `fieldset` desativou), volta ao Guardar quando a gravação acaba, salvo se o 422 o pôs num
//    campo.
// Os valores entram como texto (o React escapa-os).
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, Save } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { IndicadorCrm } from '../../components/crm/GuardaCrm';
import { alterarDefinicoes, obterDefinicoes } from '../../lib/crm/api';
import {
  TEXTO_A_CARREGAR_ROTAS,
  TEXTO_A_GUARDAR,
  TEXTO_AJUDA_TEMPO_SERVICO,
  TEXTO_DESCRICAO_ROTAS,
  TITULO_ROTAS,
  criarDefinicoesRotas,
} from '../../lib/crm/definicoesRotas';
import { criarEstadoRede } from '../../lib/crm/rede';

const API = Object.freeze({
  obterDefinicoes: () => obterDefinicoes(),
  alterarDefinicoes: (corpo) => alterarDefinicoes(corpo),
});

// Um só estado da rede para a app (os ouvintes da janela ficam enquanto a página existir).
const REDE = typeof window === 'undefined' ? null : criarEstadoRede(window, window.navigator);

const CLASSE_INVALIDO = 'aria-[invalid=true]:border-destructive';
const CLASSE_GUARDAR = 'h-11 w-full aria-disabled:cursor-not-allowed aria-disabled:opacity-50';

// O foco perdeu-se: ninguém o tem (o browser tira-o a um campo que o `fieldset` desativou).
const focoPerdido = () => document.activeElement === document.body;

function Campo({
  campo, id, refCampo, aoMudar,
}) {
  const idErro = `${id}-erro`;
  const minutos = campo.tipo === 'number';
  return (
    <div className="min-w-0 space-y-1.5">
      <Label htmlFor={id}>{campo.rotulo}</Label>
      <Input
        id={id}
        ref={refCampo}
        type={campo.tipo}
        value={campo.valor}
        onChange={(evento) => aoMudar(campo.chave, evento.target.value)}
        min={campo.min}
        max={campo.max}
        step={minutos ? 1 : 60}
        inputMode={minutos ? 'numeric' : undefined}
        className={`h-11 tabular-nums ${CLASSE_INVALIDO}`}
        aria-invalid={campo.erro ? 'true' : undefined}
        aria-describedby={campo.erro ? idErro : undefined}
        data-testid={`crm-rotas-campo-${campo.chave}`}
      />
      {campo.erro && (
        <p id={idErro} className="text-sm font-medium text-destructive" data-testid={`crm-rotas-erro-${campo.chave}`}>
          {campo.erro}
        </p>
      )}
    </div>
  );
}

export default function DefinicoesRotas() {
  const idTitulo = useId();
  const idCampos = useId();
  const idAjuda = useId();
  const campos = useRef({});
  const botaoGuardar = useRef(null);
  const [ecra, setEcra] = useState(null);
  // A primeira vista, antes de o ecrã existir: a de um ecrã acabado de criar (não pede nada).
  const [vista, setVista] = useState(() => criarDefinicoesRotas({ rede: REDE }).vista);
  // O campo que deve receber o foco quando o ecrã já o mostrar (o primeiro com o erro do 422).
  const focoPendente = useRef(null);
  const [pedidosDeFoco, setPedidosDeFoco] = useState(0);
  const aGuardarAntes = useRef(false);

  // Depois do `destruir()` (o separador saiu), o ecrã já não chama nenhum destes (definicoesRotas.test.js); o
  // `iniciar()` entrega logo a vista "a carregar".
  useEffect(() => {
    const criado = criarDefinicoesRotas({
      api: API,
      rede: REDE,
      aoMudarVista: setVista,
      aoAvisar: (texto) => toast.success(texto),
      aoFocar: (chave) => {
        focoPendente.current = chave;
        setPedidosDeFoco((n) => n + 1);
      },
    });
    setEcra(criado);
    criado.iniciar();
    return () => criado.destruir();
  }, []);

  // O foco pedido pelo ecrã, depois de o React mostrar o campo (já ativo) que o vai receber.
  useLayoutEffect(() => {
    const chave = focoPendente.current;
    if (!chave) return;
    focoPendente.current = null;
    campos.current[chave]?.focus();
  }, [pedidosDeFoco, vista]);

  // A gravação acabou e o foco perdeu-se: volta ao Guardar (depois do efeito de cima, que põe o do 422).
  useLayoutEffect(() => {
    const acabou = aGuardarAntes.current && !vista.camposDesativados;
    aGuardarAntes.current = vista.camposDesativados;
    if (acabou && focoPerdido()) botaoGuardar.current?.focus();
  }, [vista]);

  const {
    estado, falha, guardar,
  } = vista;
  const horas = vista.campos.filter((campo) => campo.grupo === null);
  const tempos = vista.campos.filter((campo) => campo.grupo !== null);
  const aMudar = (chave, valor) => ecra?.mudarCampo(chave, valor);
  const campo = (c) => (
    <Campo
      key={c.chave}
      campo={c}
      id={`${idCampos}-${c.chave}`}
      refCampo={(no) => {
        campos.current[c.chave] = no;
      }}
      aoMudar={aMudar}
    />
  );

  return (
    <section aria-labelledby={idTitulo} className="space-y-4" data-testid="crm-definicoes-rotas">
      <div className="space-y-1">
        <h2 id={idTitulo} className="font-heading text-lg font-semibold">{TITULO_ROTAS}</h2>
        <p className="text-sm text-muted-foreground">{TEXTO_DESCRICAO_ROTAS}</p>
      </div>

      {estado === 'a_carregar' && <IndicadorCrm texto={TEXTO_A_CARREGAR_ROTAS} />}

      {estado === 'falha' && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border bg-card p-8 text-center">
          <p role="alert" className="max-w-md font-medium text-destructive" data-testid="crm-rotas-falha">
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
          aria-busy={vista.camposDesativados ? 'true' : undefined}
          className="space-y-5 rounded-2xl border bg-card p-4 md:p-6"
          onSubmit={(evento) => {
            evento.preventDefault();
            ecra?.guardar();
          }}
          data-testid="crm-rotas-formulario"
        >
          {/* Enquanto grava, os campos ficam desativados (a resposta volta a preenchê-los). */}
          <fieldset disabled={vista.camposDesativados} className="m-0 min-w-0 space-y-5 border-0 p-0">
            <div className="grid gap-4 sm:grid-cols-2">
              {horas.map(campo)}
            </div>

            <div className="border-t pt-5">
              <fieldset aria-describedby={idAjuda} className="m-0 min-w-0 space-y-3 border-0 p-0" data-testid="crm-rotas-tempos">
                <legend className="mb-1 p-0 font-heading text-base font-semibold">{tempos[0].grupo}</legend>
                <p id={idAjuda} className="text-sm text-muted-foreground">{TEXTO_AJUDA_TEMPO_SERVICO}</p>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  {tempos.map(campo)}
                </div>
              </fieldset>
            </div>
          </fieldset>

          <div className="space-y-2 border-t pt-5">
            {vista.alerta && (
              <p role="alert" className="text-sm font-semibold text-destructive [overflow-wrap:anywhere]" data-testid="crm-rotas-alerta">
                {vista.alerta}
              </p>
            )}
            {/* Sempre na página (mesmo vazia), para os leitores de ecrã lerem o que lá aparecer. */}
            <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="crm-rotas-falta">
              {guardar.falta}
            </p>
            <Button
              ref={botaoGuardar}
              type="submit"
              className={CLASSE_GUARDAR}
              aria-disabled={guardar.ativo ? undefined : 'true'}
              data-testid="crm-rotas-guardar"
            >
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
