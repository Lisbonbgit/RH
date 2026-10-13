// O mapa das lojas (Leaflet 1.9.4) ligado ao React. As regras do mapa estão em
// `lib/crm/mapa.js` (com testes); aqui só se ligam ao ciclo de vida do
// componente (plano T2.25):
//  - o mapa cria-se num `useEffect`, com a área já na página (o Leaflet mede-a),
//    e destrói-se no cleanup: o `StrictMode` monta duas vezes em
//    desenvolvimento, e o Leaflet recusa um segundo mapa no mesmo elemento;
//  - mostra as lojas que recebe (as que os filtros deixam ver; `null` enquanto
//    não chegam). A primeira vista é da página (`aoPronto` entrega-lhe o mapa,
//    com `enquadrar`, `centrarEm` e `redimensionar`);
//  - se o Leaflet falhar a criar o mapa, avisa a página (`aoFalhar`);
//  - quando a área muda de tamanho (o cartão da loja, um aviso por cima, o
//    telemóvel a rodar), o Leaflet volta a medi-la (`redimensionar`).
//
// O Leaflet entra só por aqui (`import * as L`: o build ESM não tem export por
// omissão; correção "T2.25"), numa página carregada à parte (`React.lazy` em
// `rotasCrm.js`): não vai para o ficheiro principal do portal. O
// `leaflet.css` vem depois do `index.css` do portal.
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { criarMapa } from '../../lib/crm/mapa';
import './crm.css';

export default function MapaLojas({ configuracao, lojas, ocupado = false, aoPronto, aoFalhar, aoEscolherLoja, aoTocarNoMapa }) {
  const area = useRef(null);
  const [mapa, setMapa] = useState(null);

  // As funções mais recentes da página: o mapa cria-se uma vez e chama-as daqui.
  const ouvintes = useRef({});
  useLayoutEffect(() => {
    ouvintes.current = { aoPronto, aoFalhar, aoEscolherLoja, aoTocarNoMapa };
  });

  useEffect(() => {
    const elemento = area.current;
    let criado;
    try {
      criado = criarMapa({
        L,
        documento: document,
        elemento,
        configuracao,
        aoEscolherLoja: (loja, marcador) => ouvintes.current.aoEscolherLoja?.(loja, marcador),
        aoTocarNoMapa: (ponto) => ouvintes.current.aoTocarNoMapa?.(ponto),
      });
    } catch (erro) {
      console.error('[crm] o mapa não foi criado:', erro);
      ouvintes.current.aoFalhar?.();
      return undefined;
    }

    const observador = typeof ResizeObserver === 'function' ? new ResizeObserver(() => criado.redimensionar()) : null;
    observador?.observe(elemento);
    setMapa(criado);
    ouvintes.current.aoPronto?.(criado);

    return () => {
      observador?.disconnect();
      ouvintes.current.aoPronto?.(null);
      setMapa(null);
      criado.destruir();
    };
  }, [configuracao]);

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
