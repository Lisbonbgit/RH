// O mapa das lojas sobre o Google Maps, ligado ao React (plano do mapa Google, G13). As regras do mapa estão
// em `lib/crm/mapa.js` (com testes); aqui só se ligam ao ciclo de vida do componente:
//  - primeiro carrega-se a biblioteca da Google pelo nosso carregador (`lib/crm/carregadorGoogle.js`), com a
//    chave do navegador que chega no GET /api/crm/config. Só nas páginas do CRM (carregadas à parte, com
//    `React.lazy` em `rotasCrm.js`): a Google não entra no ficheiro principal do portal. As três bibliotecas
//    pedem-se no mesmo instante, por isso vão num só script;
//  - o mapa cria-se depois disso, num `useEffect`, e destrói-se no cleanup. O `StrictMode` monta duas vezes
//    em desenvolvimento: a montagem já desfeita não cria nada quando a Google chega (`ativo`), e o carregador
//    não mete um segundo script;
//  - mostra as lojas que recebe (as que os filtros deixam ver; `null` enquanto não chegam). A primeira vista é
//    da página (`aoPronto` entrega-lhe o mapa, com `enquadrar`, `centrarEm`, `redimensionar` e `focar`);
//  - tocar no ícone de um negócio abre o balão da própria Google e avisa a página (`aoTocarNumLugar`, com o
//    identificador do lugar e o ponto tocado); sem esse ouvinte, chega como um toque no mapa. Com
//    `negociosClicaveis={false}` (o planeador da F3b) os negócios não respondem;
//  - se a Google não carregar (rede, quota) ou o mapa não se criar, avisa a página (`aoFalhar`), que mostra a
//    mensagem de sempre. Uma chave recusada (um referrer que a Google não autoriza, a app instalada, uma chave
//    inválida) não faz o script falhar: a Google avisa depois (`aoFalharAutenticacao` do carregador, o
//    `gm_authFailure`), com o mapa já criado ou ainda a carregar, e a página também recebe `aoFalhar` (uma vez;
//    revisão do mapa Google, MAPA-G-1);
//  - quando a área muda de tamanho (o cartão da loja, um aviso por cima, o telemóvel a rodar), avisa o mapa
//    (`redimensionar`).
//
// O `div.crm-mapa` é o único elemento que este componente desenha, sem filhos nossos: a Google enche-o com o
// mapa, o logótipo e a atribuição, que nada nosso tapa (a regra de disposição do `crm.css`).
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { prepararGoogleMaps } from '../../lib/crm/carregadorGoogle';
import { criarMapa } from '../../lib/crm/mapa';
import './crm.css';

// As bibliotecas da Google de que o mapa precisa (a dos lugares serve o painel do negócio e a pesquisa).
const BIBLIOTECAS = ['maps', 'marker', 'places'];

export default function MapaLojas({
  configuracao,
  lojas,
  ocupado = false,
  negociosClicaveis = true,
  aoPronto,
  aoFalhar,
  aoEscolherLoja,
  aoTocarNoMapa,
  aoTocarNumLugar,
}) {
  const area = useRef(null);
  const [mapa, setMapa] = useState(null);

  // As funções mais recentes da página: o mapa cria-se uma vez e chama-as daqui.
  const ouvintes = useRef({});
  useLayoutEffect(() => {
    ouvintes.current = { aoPronto, aoFalhar, aoEscolherLoja, aoTocarNoMapa, aoTocarNumLugar };
  });

  useEffect(() => {
    const elemento = area.current;
    // Falso depois do cleanup: o que chegar depois (a Google, uma falha) já não é desta montagem.
    let ativo = true;
    let criado = null;
    let observador = null;
    // A falha já foi dada à página (a Google recusou a chave): não se cria o mapa nem se avisa outra vez.
    let falhou = false;
    let desligarRecusa = () => {};

    // Diz porquê na consola (nunca a chave) e avisa a página, uma vez por montagem.
    function avisarFalha(...porque) {
      if (!ativo || falhou) return;
      falhou = true;
      console.error(...porque);
      ouvintes.current.aoFalhar?.();
    }

    async function montar() {
      try {
        const { importar, aoFalharAutenticacao } = prepararGoogleMaps({
          janela: window,
          documento: document,
          chave: configuracao?.google?.chave,
        });
        desligarRecusa = aoFalharAutenticacao(() => avisarFalha('[crm] a Google recusou a chave do mapa (referrer, chave ou API).'));
        await Promise.all(BIBLIOTECAS.map((nome) => importar(nome)));
        if (!ativo || falhou) return;
        criado = criarMapa({
          google: window.google,
          documento: document,
          elemento,
          configuracao,
          negociosClicaveis,
          aoEscolherLoja: (loja, marcador) => ouvintes.current.aoEscolherLoja?.(loja, marcador),
          aoTocarNoMapa: (ponto) => ouvintes.current.aoTocarNoMapa?.(ponto),
          // Sem `aoTocarNumLugar` na página, o toque num negócio é um toque no mapa (como no `criarMapa`).
          aoTocarNumLugar: (lugar) => {
            const { aoTocarNumLugar: noLugar, aoTocarNoMapa: noMapa } = ouvintes.current;
            if (noLugar) noLugar(lugar);
            else noMapa?.(lugar.lat === null ? null : { lat: lugar.lat, lng: lugar.lng });
          },
        });
      } catch (erro) {
        avisarFalha('[crm] o mapa não foi criado:', erro);
        return;
      }

      observador = typeof ResizeObserver === 'function' ? new ResizeObserver(() => criado.redimensionar()) : null;
      observador?.observe(elemento);
      setMapa(criado);
      ouvintes.current.aoPronto?.(criado);
    }
    montar();

    return () => {
      ativo = false;
      desligarRecusa();
      if (!criado) return;
      observador?.disconnect();
      ouvintes.current.aoPronto?.(null);
      setMapa(null);
      criado.destruir();
    };
  }, [configuracao, negociosClicaveis]);

  useEffect(() => {
    if (mapa && Array.isArray(lojas)) mapa.mostrarLojas(lojas);
  }, [mapa, lojas]);

  return (
    <div
      ref={area}
      className="crm-mapa"
      role="region"
      aria-label="Mapa das lojas"
      aria-busy={ocupado ? 'true' : undefined}
    />
  );
}
