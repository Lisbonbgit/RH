// Os campos de uma loja (desenho original §6.2; plano T2.27), no aspeto do
// portal: nome*, fase* (pastilhas com a cor do pino, um toque), região,
// telefone, pessoa de contacto, morada, código postal, localidade e notas. Com
// `ficha` (a ficha da loja, T2.28), também o horário de receção (duas janelas,
// `type="time"`) e os dias fechada, antes das notas. Porta de
// public/assets/js/componentes/formulario-loja.js do CRM autónomo.
//
// Só desenha o estado de `lib/crm/formularioLoja.js` (com testes): os
// `valores`, os `erros` da API junto a cada campo (com `aria-invalid` e
// `aria-describedby`), as `opcoesRegiao` e o `valorRegiao`. O que a pessoa
// muda vai para `aoMudar(campo, valor)` (a região já como uuid ou null), a
// fase também para `aoMudarFase(fase)` (a ficha grava-a logo) e os dias para
// `aoAlternarDia(dia, marcado)`. Pela `ref`, `focar(campo)` (o primeiro campo
// com erro de um 422).
//
// Os dados entram como texto (o React escapa-os). Os campos não aceitam o
// preenchimento automático do browser: são os dados da loja, não os de quem
// escreve (desenho original §9).
import React, { forwardRef, useId, useImperativeHandle, useRef } from 'react';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Textarea } from '../ui/textarea';
import {
  CAMPOS, DIAS, ROTULO_DIAS, ROTULO_FASE, ROTULO_HORARIO, TEXTO_SEM_HORARIO, camposJanelas, opcoesFase,
  regiaoDoSeletor,
} from '../../lib/crm/formularioLoja';
import './crm.css';

const CLASSE_PASTILHA = 'inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border bg-background py-2 pl-2.5 pr-3.5 text-sm font-semibold transition-colors has-[:checked]:border-primary has-[:checked]:bg-primary/10 has-[:checked]:text-primary has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring';
const CLASSE_ERRO = 'text-sm font-medium text-destructive [overflow-wrap:anywhere]';
// O campo com erro fica com a borda a vermelho (além da mensagem por baixo).
const CLASSE_INVALIDO = 'aria-[invalid=true]:border-destructive';

// O asterisco dos obrigatórios não é lido (o campo diz que é obrigatório).
function Obrigatorio() {
  return <span aria-hidden="true" className="text-destructive"> *</span>;
}

// As janelas do horário, cada uma com o início e o fim (pela ordem de `camposJanelas`).
function janelasDoHorario() {
  const janelas = [];
  for (const campo of camposJanelas()) {
    const ultima = janelas[janelas.length - 1];
    if (ultima?.nome === campo.janela) ultima.campos.push(campo);
    else janelas.push({ nome: campo.janela, campos: [campo] });
  }
  return janelas;
}

const FormularioLoja = forwardRef(function FormularioLoja({
  valores, erros = {}, opcoesRegiao, valorRegiao, ficha = false, desativado = false, aoMudar, aoMudarFase, aoAlternarDia,
}, ref) {
  const base = useId();
  const id = (campo) => `${base}-${campo.replace(/_/g, '-')}`;
  const idErro = (campo) => `${id(campo)}-erro`;
  const nos = useRef({});
  const guardarNo = (campo) => (no) => {
    nos.current[campo] = no;
  };

  useImperativeHandle(ref, () => ({
    focar(campo) {
      if (campo === 'fase') {
        (nos.current[`fase-${valores.fase}`] ?? nos.current[`fase-${opcoesFase()[0].valor}`])?.focus();
      } else if (campo === 'dias_fechada') {
        nos.current[`dia-${DIAS[0].valor}`]?.focus();
      } else {
        nos.current[campo]?.focus();
      }
    },
  }), [valores.fase]);

  // Os atributos de erro de um campo: o erro por baixo, ligado a ele para o leitor de ecrã o ler com o campo.
  const comErro = (campo) => (erros[campo]
    ? { 'aria-invalid': 'true', 'aria-describedby': idErro(campo) }
    : {});
  const erro = (campo) => (erros[campo]
    ? <p id={idErro(campo)} className={CLASSE_ERRO} data-testid={`crm-erro-${campo}`}>{erros[campo]}</p>
    : null);

  function campoTexto(campo) {
    const def = CAMPOS[campo];
    const comuns = {
      id: id(campo),
      name: campo,
      ref: guardarNo(campo),
      value: valores[campo] ?? '',
      onChange: (evento) => aoMudar?.(campo, evento.target.value),
      autoComplete: def.autoComplete,
      maxLength: def.maxLength,
      disabled: desativado,
      'data-testid': `crm-campo-${campo}`,
      ...comErro(campo),
    };
    return (
      <div key={campo} className="space-y-1.5">
        <Label htmlFor={id(campo)}>
          {def.rotulo}
          {def.obrigatorio && <Obrigatorio />}
        </Label>
        {def.tag === 'textarea'
          ? <Textarea rows={def.linhas} className={`text-base md:text-sm ${CLASSE_INVALIDO}`} {...comuns} />
          : (
            <Input
              type={def.tipo}
              inputMode={def.inputMode}
              placeholder={def.placeholder}
              required={def.obrigatorio}
              className={`h-11 ${CLASSE_INVALIDO}`}
              {...comuns}
            />
          )}
        {erro(campo)}
      </div>
    );
  }

  const campoFase = (
    <fieldset key="fase" className="m-0 min-w-0 space-y-2 border-0 p-0" {...comErro('fase')} data-testid="crm-campo-fase">
      <legend className="mb-1.5 p-0 text-sm font-medium">
        {ROTULO_FASE}
        <Obrigatorio />
      </legend>
      <div className="flex flex-wrap gap-2">
        {opcoesFase().map(({ valor, rotulo, classeCor }) => (
          // O rótulo envolve a opção: a pastilha inteira (44 px) é área de toque.
          <label key={valor} htmlFor={`${id('fase')}-${valor}`} className={CLASSE_PASTILHA}>
            <input
              type="radio"
              id={`${id('fase')}-${valor}`}
              name={`${base}-fase`}
              value={valor}
              ref={guardarNo(`fase-${valor}`)}
              checked={valores.fase === valor}
              disabled={desativado}
              onChange={() => {
                aoMudar?.('fase', valor);
                aoMudarFase?.(valor);
              }}
              className="h-[18px] w-[18px] shrink-0 accent-primary"
            />
            <span aria-hidden="true" className={classeCor} />
            {rotulo}
          </label>
        ))}
      </div>
      {erro('fase')}
    </fieldset>
  );

  const campoRegiao = (
    <div key="regiao_id" className="space-y-1.5">
      <Label htmlFor={id('regiao_id')}>{CAMPOS.regiao_id.rotulo}</Label>
      <Select value={valorRegiao} onValueChange={(valor) => aoMudar?.('regiao_id', regiaoDoSeletor(valor))} disabled={desativado}>
        <SelectTrigger id={id('regiao_id')} ref={guardarNo('regiao_id')} className={`h-11 ${CLASSE_INVALIDO}`} data-testid="crm-campo-regiao_id" {...comErro('regiao_id')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {opcoesRegiao.map((opcao) => (
            <SelectItem key={opcao.valor} value={opcao.valor} className="min-h-11">
              {opcao.texto}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {erro('regiao_id')}
    </div>
  );

  const campoHorario = ficha && (
    <fieldset key="horario" className="m-0 min-w-0 space-y-2 border-0 p-0" aria-describedby={`${base}-horario-ajuda`}>
      <legend className="mb-1 p-0 text-sm font-medium">{ROTULO_HORARIO}</legend>
      <p id={`${base}-horario-ajuda`} className="text-sm text-muted-foreground">{TEXTO_SEM_HORARIO}</p>
      {janelasDoHorario().map((janela) => (
        <div key={janela.nome} role="group" aria-label={janela.nome} className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          <span aria-hidden="true" className="col-span-2 text-sm font-semibold text-muted-foreground">{janela.nome}</span>
          {janela.campos.map(({ campo, parte }) => (
            <div key={campo} className="min-w-0 space-y-1.5">
              {/* No ecrã lê-se "Início"/"Fim"; o leitor de ecrã lê o rótulo inteiro ("Início da 1.ª janela"). */}
              <Label htmlFor={id(campo)} className="font-normal">
                {parte}
                <span className="sr-only">{` da ${janela.nome}`}</span>
              </Label>
              <Input
                type="time"
                step={60}
                id={id(campo)}
                name={campo}
                ref={guardarNo(campo)}
                value={valores[campo] ?? ''}
                onChange={(evento) => aoMudar?.(campo, evento.target.value)}
                disabled={desativado}
                className={`h-11 ${CLASSE_INVALIDO}`}
                data-testid={`crm-campo-${campo}`}
                {...comErro(campo)}
              />
              {erro(campo)}
            </div>
          ))}
        </div>
      ))}
    </fieldset>
  );

  const campoDias = ficha && (
    <fieldset key="dias" className="m-0 min-w-0 space-y-2 border-0 p-0" {...comErro('dias_fechada')} data-testid="crm-campo-dias_fechada">
      <legend className="mb-1.5 p-0 text-sm font-medium">{ROTULO_DIAS}</legend>
      <div className="flex flex-wrap gap-2">
        {DIAS.map(({ valor, rotulo }) => (
          <label key={valor} htmlFor={`${id('dias_fechada')}-${valor}`} className={CLASSE_PASTILHA}>
            <input
              type="checkbox"
              id={`${id('dias_fechada')}-${valor}`}
              value={valor}
              ref={guardarNo(`dia-${valor}`)}
              checked={Array.isArray(valores.dias_fechada) && valores.dias_fechada.includes(valor)}
              disabled={desativado}
              onChange={(evento) => aoAlternarDia?.(valor, evento.target.checked)}
              className="h-[18px] w-[18px] shrink-0 accent-primary"
            />
            {rotulo}
          </label>
        ))}
      </div>
      {erro('dias_fechada')}
    </fieldset>
  );

  return (
    <div className="space-y-4" data-testid="crm-formulario-loja">
      {campoTexto('nome')}
      {campoFase}
      {campoRegiao}
      {['telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade'].map(campoTexto)}
      {campoHorario}
      {campoDias}
      {campoTexto('notas')}
    </div>
  );
});

export default FormularioLoja;
