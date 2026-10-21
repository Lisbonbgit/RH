// Um texto em partes ({texto, url}), como o seletor da localização o recebe (plano do mapa Google, G14: saiu
// tal e qual do campo de pesquisa da Geoapify, que já não existe). Serve a "Morada sugerida: …" do seletor:
// a da Google só em texto e a do GPS com "· Powered by Geoapify" em ligação.
import React from 'react';

// Um texto em partes ({texto, url}): cada parte com `url` é uma ligação (abre noutro separador), as outras são
// texto. As ligações vêm só das constantes de `atribuicoes.js` (o texto dos dados nunca traz `url`).
export function Partes({ partes }) {
  return partes.map((parte, i) => (parte.url === null
    ? <React.Fragment key={i}>{parte.texto}</React.Fragment>
    : (
      <a key={i} href={parte.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-foreground">
        {parte.texto}
      </a>
    )));
}
