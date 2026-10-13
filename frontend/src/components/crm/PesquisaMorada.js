// O campo "Pesquisar morada" do seletor da localização (desenho original §6.2;
// plano T2.26). Porta de public/assets/js/componentes/pesquisa-morada.js do
// CRM autónomo, no aspeto do portal.
//
// Só desenha a `vista` do campo (`lib/crm/pesquisaMorada.js`, com testes) e
// passa-lhe o que a pessoa faz: o texto (`aoEscrever`), as teclas (`aoTecla`,
// que diz se a tecla é do campo: setas, Enter e Escape) e a sugestão em que
// tocou (`aoEscolher`). O campo nasce uma vez com o seletor
// (`SeletorLocalizacao`), que o cancela no cleanup do efeito: uma resposta
// tardia não mexe num ecrã que já saiu.
//
//  - Combobox: as setas marcam a sugestão ativa (`aria-activedescendant`), o
//    Enter escolhe-a e nunca submete o formulário à volta, o Escape fecha.
//  - A lista fica por baixo do campo, no fluxo da página: não tapa o mapa nem
//    a atribuição dos mosaicos. Tocar numa sugestão não tira o foco do campo
//    (no telemóvel, o toque chegava a fechar o teclado em vez de escolher).
//  - "Powered by Geoapify" sempre à vista por baixo (desenho original §9), com
//    a ligação, montado só a partir de `ATRIBUICOES.pesquisa.partes`.
// As sugestões e a mensagem entram como texto (o React escapa-as).
import React, { useEffect } from 'react';
import { Search } from 'lucide-react';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { ATRIBUICOES } from '../../lib/crm/atribuicoes';
import { TEXTO_MAXIMO, TEXTO_PESQUISAR_MORADA, TEXTO_SUGESTOES } from '../../lib/crm/pesquisaMorada';

// Um texto em partes ({texto, url}): cada parte com `url` é uma ligação (abre noutro separador), as outras são
// texto. Serve o "Powered by Geoapify" daqui e a "Morada sugerida: … · Powered by Geoapify" do seletor; as
// ligações vêm só das constantes de `atribuicoes.js` (o texto dos dados nunca traz `url`).
export function Partes({ partes }) {
  return partes.map((parte, i) => (parte.url === null
    ? <React.Fragment key={i}>{parte.texto}</React.Fragment>
    : (
      <a key={i} href={parte.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-foreground">
        {parte.texto}
      </a>
    )));
}

// id: a base dos ids do campo (useId do seletor); vista: a do campo; desativado: ainda sem o seletor.
export default function PesquisaMorada({ id, vista, desativado = false, aoEscrever, aoTecla, aoEscolher }) {
  const idLista = `${id}-sugestoes`;
  const idEstado = `${id}-estado`;
  const idSugestao = (i) => `${id}-sugestao-${i}`;
  const ativa = vista.aberta && vista.ativa >= 0 ? idSugestao(vista.ativa) : undefined;

  // A sugestão ativa (escolhida com as setas) fica à vista dentro da lista.
  useEffect(() => {
    if (ativa) document.getElementById(ativa)?.scrollIntoView?.({ block: 'nearest' });
  }, [ativa]);

  return (
    <div className="space-y-1.5" data-estado={vista.estado} data-testid="crm-pesquisa-morada">
      <Label htmlFor={id}>{TEXTO_PESQUISAR_MORADA}</Label>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input
          id={id}
          type="search"
          className="h-11 appearance-none pl-9"
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="search"
          maxLength={TEXTO_MAXIMO}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={vista.aberta ? 'true' : 'false'}
          aria-controls={idLista}
          aria-describedby={idEstado}
          aria-activedescendant={ativa}
          value={vista.texto}
          disabled={desativado}
          onChange={(evento) => aoEscrever(evento.target.value)}
          onKeyDown={(evento) => {
            if (aoTecla(evento.key)) evento.preventDefault();
          }}
        />
      </div>
      <ul
        id={idLista}
        role="listbox"
        aria-label={TEXTO_SUGESTOES}
        hidden={!vista.aberta}
        className="overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md"
      >
        {vista.sugestoes.map((sugestao, i) => (
          <li
            key={i}
            id={idSugestao(i)}
            role="option"
            aria-selected={i === vista.ativa ? 'true' : 'false'}
            className="flex min-h-11 cursor-pointer items-center border-t px-3 py-2.5 text-sm [overflow-wrap:anywhere] first:border-t-0 hover:bg-accent hover:text-accent-foreground aria-selected:bg-accent aria-selected:text-accent-foreground"
            // O foco fica no campo: no telemóvel, o toque chega à sugestão em vez de se perder a fechar o teclado.
            onMouseDown={(evento) => evento.preventDefault()}
            onClick={() => aoEscolher(i)}
          >
            {sugestao.rotulo}
          </li>
        ))}
      </ul>
      <p
        id={idEstado}
        aria-live="polite"
        className={vista.estado === 'erro' ? 'text-sm font-semibold text-destructive' : 'text-sm text-muted-foreground'}
      >
        {vista.mensagem}
      </p>
      <p className="text-xs text-muted-foreground" data-testid="crm-pesquisa-morada-atribuicao">
        <Partes partes={ATRIBUICOES.pesquisa.partes} />
      </p>
    </div>
  );
}
