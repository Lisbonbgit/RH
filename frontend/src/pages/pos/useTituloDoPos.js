import { useEffect } from 'react';

// O separador do browser diz "Lisbonb - POS" enquanto o POS estiver aberto, e
// devolve o título ao que estava quando se sai.
//
// **Porque não se muda o `<title>` do `public/index.html`.** Aquele título é do
// PORTAL INTEIRO — o RH, o Estoque, a Faturação, tudo. Mudá-lo ali renomeava
// todos os ecrãs da casa para "Lisbonb - POS", incluindo os que nada têm que
// ver com o balcão. O título é do ECRÃ que está à frente, e é por isso que
// mora aqui e não lá.
//
// **E devolve-se o que lá estava, em vez de escrever "Gestão Lisbonb" à mão.**
// Escrever o nome do portal aqui era guardar uma segunda cópia dele: no dia em
// que alguém mudasse o `index.html`, sair do POS punha no separador um nome que
// já não existe. Guarda-se o que estava, seja ele qual for.
export const TITULO_DO_POS = 'Lisbonb - POS';

export default function useTituloDoPos(titulo = TITULO_DO_POS) {
  useEffect(() => {
    const anterior = document.title;
    document.title = titulo;
    return () => { document.title = anterior; };
  }, [titulo]);
}
