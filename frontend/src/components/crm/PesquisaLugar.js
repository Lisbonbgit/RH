// O campo "Pesquisar morada ou lugar (Google)" do seletor da localização (plano do mapa Google, G14; adenda
// §1.2 e §6.3). O campo é o elemento de pesquisa da própria Google, criado por `criarPesquisaLugar` em
// `lib/crm/lugarGoogle.js` (dentro do seletor, com o mapa); este componente só lhe dá um sítio na página:
//  - um rótulo visível (`<p id>`) e, por baixo, um contentor que o nomeia (`aria-labelledby`: um `<label>` não
//    chega ao campo de texto da Google, que vive no shadow DOM dela);
//  - o elemento junta-se ao contentor num `useEffect` e sai no cleanup (e quando o seletor o troca ou o tira);
//  - sem elemento (sem mapa, ou sem a biblioteca dos lugares) não há contentor.
// Nada se lê nem se escreve dentro do elemento: as sugestões, o texto e a atribuição são da Google.
//
// {id, elemento, ativa}: `id` para o rótulo; `elemento` o de `vista.pesquisa.elemento`; `ativa` o de
// `vista.pesquisa.ativa` (`aria-disabled` no contentor quando não está).
import React, { useEffect, useRef } from 'react';
import { TEXTO_PESQUISAR_LUGAR } from '../../lib/crm/lugarGoogle';

export default function PesquisaLugar({ id, elemento, ativa }) {
  const contentor = useRef(null);

  useEffect(() => {
    const destino = contentor.current;
    if (!destino || !elemento) return undefined;
    destino.appendChild(elemento);
    return () => {
      if (elemento.parentNode === destino) destino.removeChild(elemento);
    };
  }, [elemento]);

  return (
    <div className="space-y-1.5" data-testid="crm-pesquisa-lugar">
      <p id={id} className="text-sm font-medium leading-none">{TEXTO_PESQUISAR_LUGAR}</p>
      {elemento && (
        <div ref={contentor} role="group" aria-labelledby={id} aria-disabled={!ativa} className="min-h-11" />
      )}
    </div>
  );
}
