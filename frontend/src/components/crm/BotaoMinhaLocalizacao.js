// O botão "A minha localização" da barra de cima dos mapas do CRM (desenho de 2026-11-06). As regras estão em
// `lib/crm/minhaLocalizacao.js` (com testes); aqui só se ligam ao ciclo de vida:
//  - `mapa` é o do `MapaLojas` (o que a página recebe no `aoPronto`): `null` enquanto não está pronto e enquanto é
//    recriado. Por isso o botão não espera por ele: o GPS arranca ao toque e o ponto desenha-se no mapa que chegar;
//  - as regras criam-se num `useEffect` e destroem-se no cleanup: sair do ecrã para o GPS e tira o ponto. O
//    `StrictMode` monta duas vezes em desenvolvimento, sem efeito: nada corre antes do toque;
//  - `aoCentrar(mapa)` diz à página que o mapa foi centrado na pessoa, para a primeira vista não desfazer esse centro
//    (corre antes dela: os efeitos dos filhos vêm primeiro). Lê-se de um `ref`: uma função nova não recria as regras;
//  - enquanto procura, o botão fica com `aria-disabled` (o foco não se perde) e um toque não pede outra vez;
//  - os erros são toasts do sonner, como nos outros ecrãs do CRM.
// É um só elemento: a barra (`.crm-mapa__barra`) devolve os toques aos filhos diretos.
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, LocateFixed } from 'lucide-react';
import { Button } from '../ui/button';
import { VISTA_INICIAL, criarMinhaLocalizacao } from '../../lib/crm/minhaLocalizacao';

export default function BotaoMinhaLocalizacao({ mapa, aoCentrar }) {
  const [vista, setVista] = useState(VISTA_INICIAL);
  const controlo = useRef(null);

  // A função mais recente da página: as regras criam-se uma vez e chamam-na daqui.
  const ouvinte = useRef(aoCentrar);
  useLayoutEffect(() => {
    ouvinte.current = aoCentrar;
  });

  useEffect(() => {
    const criado = criarMinhaLocalizacao({
      geolocation: typeof navigator === 'undefined' ? undefined : navigator.geolocation,
      documento: document,
      aoMudarVista: setVista,
      aoAvisar: (texto) => toast.error(texto),
      aoCentrar: (centrado) => ouvinte.current?.(centrado),
    });
    controlo.current = criado;
    return () => {
      criado.destruir();
      controlo.current = null;
    };
  }, []);

  // Depois do efeito de cima: no `StrictMode`, também as regras novas recebem o mapa.
  useEffect(() => {
    controlo.current?.usarMapa(mapa);
  }, [mapa]);

  const Icone = vista.aProcurar ? Loader2 : LocateFixed;
  const classeIcone = vista.aProcurar ? 'h-4 w-4 animate-spin motion-reduce:animate-none' : 'h-4 w-4';

  return (
    <Button
      type="button"
      variant={vista.ligado ? 'default' : 'outline'}
      className={`h-11 shadow-md aria-disabled:cursor-wait aria-disabled:opacity-70 ${vista.ligado ? '' : 'bg-background'}`}
      aria-label={vista.rotulo}
      aria-pressed={vista.ligado}
      aria-disabled={vista.aProcurar ? 'true' : undefined}
      onClick={() => controlo.current?.tocar()}
      data-estado={vista.estado}
      data-testid="crm-mapa-minha-localizacao"
    >
      <Icone className={classeIcone} aria-hidden="true" />
      <span className="hidden sm:inline">{vista.texto}</span>
    </Button>
  );
}
