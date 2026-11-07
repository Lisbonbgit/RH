// Os campos de uma loja (desenho original §6.2; plano T2.27), no aspeto do
// portal: nome*, fase* (pastilhas com a cor do pino, um toque), região,
// telefone, pessoa de contacto, morada, código postal, localidade e notas. Com
// `ficha` (a ficha da loja, T2.28), também o Instagram e o site (2026-10-13,
// dois campos de texto a seguir à localidade), o horário de receção (duas
// janelas, `type="time"`) e os dias fechada, antes das notas, e o bloco
// "Consumo e marcas" (desenho de 2026-11-07, §2), depois delas. Porta de
// public/assets/js/componentes/formulario-loja.js do CRM autónomo.
//
// Só desenha o estado de `lib/crm/formularioLoja.js` (com testes): os
// `valores`, os `erros` da API junto a cada campo (com `aria-invalid` e
// `aria-describedby`), as `opcoesRegiao` e o `valorRegiao`. O que a pessoa
// muda vai para `aoMudar(campo, valor)` (a região já como uuid ou null), a
// fase também para `aoMudarFase(fase)` (a ficha grava-a logo) e os dias para
// `aoAlternarDia(dia, marcado)`. A caixa "O cliente não quer revelar" e as
// respostas aos sorbets vão para o `aoMudar`, com o booleano ou o `null`. Pela
// `ref`, `focar(campo)` (o primeiro campo com erro de um 422). `dicas` ({campo: texto}, só nos campos de texto) põe uma
// dica por baixo do campo, ligada a ele por `aria-describedby` antes do erro
// (a nova loja que vem de um negócio da Google: a dica do nome, plano do mapa
// Google, G16).
//
// Com a caixa marcada, o campo da marca fica vazio e desativado, sem tocar no
// texto dos `valores`: desmarcar repõe-no. O campo "Quais?" só existe com Sim.
//
// Os dados entram como texto (o React escapa-os). Os campos não aceitam o
// preenchimento automático do browser: são os dados da loja, não os de quem
// escreve (desenho original §9).
import React, { forwardRef, useId, useImperativeHandle, useRef } from 'react';
import { TriangleAlert } from 'lucide-react';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Textarea } from '../ui/textarea';
import {
  CAMPOS, CLASSE_PASTILHA, DIAS, OPCOES_OUTROS_SORBETS, ROTULO_CONSUMO_MARCAS, ROTULO_DIAS, ROTULO_FASE,
  ROTULO_HORARIO, ROTULO_MARCA_NAO_REVELA, ROTULO_OUTROS_SORBETS, TEXTO_AVISO_MARCA, TEXTO_SEM_HORARIO, camposJanelas,
  opcoesFase, regiaoDoSeletor,
} from '../../lib/crm/formularioLoja';
import './crm.css';

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
  valores, erros = {}, opcoesRegiao, valorRegiao, ficha = false, desativado = false, dicas = {}, aoMudar, aoMudarFase,
  aoAlternarDia,
}, ref) {
  const base = useId();
  const id = (campo) => `${base}-${campo.replace(/_/g, '-')}`;
  const idErro = (campo) => `${id(campo)}-erro`;
  const idDica = (campo) => `${id(campo)}-dica`;
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
      } else if (campo === 'outros_sorbets') {
        const escolhida = OPCOES_OUTROS_SORBETS.find((opcao) => opcao.valor === valores.outros_sorbets);
        nos.current[`sorbets-${(escolhida ?? OPCOES_OUTROS_SORBETS[0]).chave}`]?.focus();
      } else {
        nos.current[campo]?.focus();
      }
    },
  }), [valores.fase, valores.outros_sorbets]);

  // Os atributos de erro de um campo: o erro por baixo, ligado a ele para o leitor de ecrã o ler com o campo.
  const comErro = (campo) => (erros[campo]
    ? { 'aria-invalid': 'true', 'aria-describedby': idErro(campo) }
    : {});
  const erro = (campo) => (erros[campo]
    ? <p id={idErro(campo)} className={CLASSE_ERRO} data-testid={`crm-erro-${campo}`}>{erros[campo]}</p>
    : null);

  // A dica de um campo de texto (em texto, não vazia), ou null.
  const dica = (campo) => {
    const texto = dicas?.[campo];
    return typeof texto === 'string' && texto !== '' ? texto : null;
  };

  const marcaPorRevelar = valores.marca_nao_revela === true;

  function campoTexto(campo) {
    const def = CAMPOS[campo];
    const textoDica = dica(campo);
    // A marca por revelar: vazio e desativado à vista, com o texto guardado nos `valores`.
    const bloqueado = campo === 'marca_atual' && marcaPorRevelar;
    // O leitor de ecrã lê a dica e depois o erro, se houver.
    const descricao = [textoDica !== null ? idDica(campo) : null, erros[campo] ? idErro(campo) : null]
      .filter((valor) => valor !== null)
      .join(' ');
    const comuns = {
      id: id(campo),
      name: campo,
      ref: guardarNo(campo),
      value: bloqueado ? '' : valores[campo] ?? '',
      onChange: (evento) => aoMudar?.(campo, evento.target.value),
      autoComplete: def.autoComplete,
      maxLength: def.maxLength,
      disabled: desativado || bloqueado,
      'data-testid': `crm-campo-${campo}`,
      ...comErro(campo),
      'aria-describedby': descricao === '' ? undefined : descricao,
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
        {textoDica !== null && (
          <p id={idDica(campo)} className="text-sm text-muted-foreground [overflow-wrap:anywhere]" data-testid={`crm-dica-${campo}`}>
            {textoDica}
          </p>
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

  const blocoConsumo = ficha && (
    <section aria-labelledby={`${base}-consumo`} className="space-y-4 border-t pt-5" data-testid="crm-bloco-consumo">
      <h2 id={`${base}-consumo`} className="font-heading text-lg font-semibold">{ROTULO_CONSUMO_MARCAS}</h2>
      {campoTexto('consumo_semanal')}
      {campoTexto('marca_atual')}
      <div className="space-y-2">
        <label htmlFor={id('marca_nao_revela')} className={CLASSE_PASTILHA}>
          <input
            type="checkbox"
            id={id('marca_nao_revela')}
            name="marca_nao_revela"
            ref={guardarNo('marca_nao_revela')}
            checked={marcaPorRevelar}
            disabled={desativado}
            onChange={(evento) => aoMudar?.('marca_nao_revela', evento.target.checked)}
            className="h-[18px] w-[18px] shrink-0 accent-primary"
            data-testid="crm-campo-marca_nao_revela"
            {...comErro('marca_nao_revela')}
          />
          {ROTULO_MARCA_NAO_REVELA}
        </label>
        {/* Sempre na página (mesmo vazio), para os leitores de ecrã lerem o que lá aparecer. */}
        <div aria-live="polite">
          {marcaPorRevelar && (
            <p
              className="flex items-center gap-2 rounded-lg border border-warning bg-warning/10 px-3 py-2 text-sm font-semibold text-warning-strong"
              data-testid="crm-aviso-marca"
            >
              <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
              {TEXTO_AVISO_MARCA}
            </p>
          )}
        </div>
        {erro('marca_nao_revela')}
      </div>
      <fieldset className="m-0 min-w-0 space-y-2 border-0 p-0" {...comErro('outros_sorbets')} data-testid="crm-campo-outros_sorbets">
        <legend className="mb-1.5 p-0 text-sm font-medium">{ROTULO_OUTROS_SORBETS}</legend>
        <div className="flex flex-wrap gap-2">
          {OPCOES_OUTROS_SORBETS.map(({ chave, valor, rotulo }) => (
            <label key={chave} htmlFor={`${id('outros_sorbets')}-${chave}`} className={CLASSE_PASTILHA}>
              <input
                type="radio"
                id={`${id('outros_sorbets')}-${chave}`}
                name={`${base}-outros-sorbets`}
                value={chave}
                ref={guardarNo(`sorbets-${chave}`)}
                checked={valores.outros_sorbets === valor}
                disabled={desativado}
                onChange={() => aoMudar?.('outros_sorbets', valor)}
                className="h-[18px] w-[18px] shrink-0 accent-primary"
              />
              {rotulo}
            </label>
          ))}
        </div>
        {erro('outros_sorbets')}
      </fieldset>
      {valores.outros_sorbets === true && campoTexto('outros_sorbets_quais')}
    </section>
  );

  return (
    <div className="space-y-4" data-testid="crm-formulario-loja">
      {campoTexto('nome')}
      {campoFase}
      {campoRegiao}
      {['telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade'].map(campoTexto)}
      {ficha && ['instagram', 'site'].map(campoTexto)}
      {campoHorario}
      {campoDias}
      {campoTexto('notas')}
      {blocoConsumo}
    </div>
  );
});

export default FormularioLoja;
