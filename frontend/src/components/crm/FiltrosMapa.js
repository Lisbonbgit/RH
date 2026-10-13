// Os filtros do mapa (desenho original §6.1; plano T2.25): "N lojas" e o botão
// "Filtros", que abre um painel com uma caixa por fase (com a cor do pino, pela
// ordem do funil) e a região (Todas, Sem região, as regiões). Porta de
// public/assets/js/componentes/filtros-mapa.js do CRM autónomo. O "só com
// pendentes" chega na F5.
//
// Só mostra e recolhe a escolha: as regras estão em `lib/crm/filtros.js` (com
// testes), e quem guarda e aplica os filtros é a página. Com filtros ativos o
// botão fica cheio, para se perceber que faltam lojas no mapa. O painel fecha
// com Escape (devolve o foco ao botão) e ao tocar fora dele, no mapa incluído.
// Os nomes das regiões entram como texto.
//
// Devolve um fragmento: a contagem e o botão ficam lado a lado na barra de
// cima do mapa, que os posiciona.
import React, { useId } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { Button } from '../ui/button';
import { Checkbox } from '../ui/checkbox';
import { Label } from '../ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { FASES, FUNIL } from '../../lib/crm/fases';
import { filtrosAtivos, normalizarFiltros, opcoesRegiao, textoNumeroLojas } from '../../lib/crm/filtros';
import './crm.css';

// filtros: os filtros em vigor (normalizados, com as fases num Set);
// regioes: a lista do GET /api/crm/regioes (null até chegar, ou se falhou);
// contagem: quantas lojas estão no mapa (null esconde: ainda não chegaram);
// aberto/aoAbrir: o painel (a página fecha-o quando se toca no mapa);
// aoMudar(filtros): a pessoa mudou a escolha (filtros já normalizados).
export default function FiltrosMapa({ filtros, regioes, contagem, aberto, aoAbrir, aoMudar }) {
  const id = useId();
  const idRegiao = `${id}-regiao`;
  const ativos = filtrosAtivos(filtros);

  function mudarFase(fase, marcada) {
    const fases = FUNIL.filter((f) => (f === fase ? marcada : filtros.fases.has(f)));
    aoMudar(normalizarFiltros({ fases, regiao: filtros.regiao }));
  }

  function mudarRegiao(regiao) {
    aoMudar(normalizarFiltros({ fases: filtros.fases, regiao }));
  }

  return (
    <>
      <p
        aria-live="polite"
        hidden={contagem === null}
        className="m-0 whitespace-nowrap rounded-full bg-background/95 px-3 py-1 text-sm font-semibold text-foreground shadow-md"
        data-testid="crm-mapa-contagem"
      >
        {contagem === null ? '' : textoNumeroLojas(contagem)}
      </p>
      <Popover open={aberto} onOpenChange={aoAbrir}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant={ativos ? 'default' : 'outline'}
            className={`h-11 shadow-md ${ativos ? '' : 'bg-background'}`}
            data-ativos={String(ativos)}
            data-testid="crm-mapa-filtros"
          >
            <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
            Filtros
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          collisionPadding={8}
          aria-label="Filtros"
          className="max-h-[var(--radix-popover-content-available-height)] w-[min(20rem,calc(100vw-2rem))] overflow-y-auto"
        >
          <fieldset className="m-0 min-w-0 border-0 p-0">
            <legend className="mb-1 p-0 font-heading font-bold">Fase</legend>
            {FUNIL.map((fase) => {
              const idFase = `${id}-fase-${fase}`;
              return (
                <div key={fase} className="flex min-h-11 items-center gap-3">
                  <Checkbox
                    id={idFase}
                    checked={filtros.fases.has(fase)}
                    onCheckedChange={(marcada) => mudarFase(fase, marcada === true)}
                  />
                  <Label htmlFor={idFase} className="flex min-h-11 flex-1 cursor-pointer items-center gap-2.5 font-semibold">
                    <span aria-hidden="true" className={`crm-amostra-fase pino--${fase}`} />
                    {FASES[fase].rotulo}
                  </Label>
                </div>
              );
            })}
          </fieldset>
          <div className="mt-3 space-y-2 pb-1">
            <Label htmlFor={idRegiao} className="font-heading font-bold">
              Região
            </Label>
            <Select value={String(filtros.regiao)} onValueChange={mudarRegiao}>
              <SelectTrigger id={idRegiao} className="h-11">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {opcoesRegiao(filtros, regioes).map((opcao) => (
                  <SelectItem key={opcao.valor} value={opcao.valor} className="min-h-11">
                    {opcao.texto}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </PopoverContent>
      </Popover>
    </>
  );
}
