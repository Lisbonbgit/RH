import { useCallback, useEffect, useRef, useState } from 'react';
import { getEstadoImpressao } from '../../lib/pos';

// **Há programa de impressão a ouvir nesta loja?** — a pergunta que decide se
// os botões de imprimir funcionam ou se dizem porque não.
//
// Uma loja onde ninguém instalou o programa (`agente_impressao/`) não pode ter
// um botão que parece funcionar: o toque entrava na fila do servidor, caducava
// meia hora depois e ninguém sabia de nada. A operadora dava o cliente por
// servido, e o papel — que é obrigação legal, e é o QR que a app de fidelização
// lê — nunca existiu.
//
// **De 20 em 20 segundos**, e não de 2 em 2: isto não é o que faz o papel sair
// (quem o faz é o programa da loja a perguntar ao servidor), é só o que o ecrã
// mostra. O servidor considera o programa vivo até 90 s sem dar sinal
// (`impressao._AGENTE_VIVO_SEGUNDOS`), por isso 20 s vê a mudança quatro vezes
// antes de ela poder ser verdade — e não põe cinco lojas a bater no servidor
// pelo estado de uns botões.
//
// **Um erro de rede NÃO apaga o que se sabia.** Se a pergunta falhar, mantém-se
// o último estado conhecido: uma falha de dois segundos na rede da loja não
// pode desligar os botões todos do balcão a meio de uma venda. O que estava a
// funcionar continua a parecer que funciona até haver uma resposta que diga o
// contrário — e se o programa tiver mesmo morrido, a resposta seguinte diz-lo.
export const INTERVALO_ESTADO_IMPRESSAO_MS = 20000;

export default function useEstadoDaImpressao(activo = true) {
  const [estado, setEstado] = useState(null);
  // `useRef` e não estado: só serve para o efeito de limpeza não escrever num
  // componente já desmontado (a operadora que sai do POS a meio da pergunta).
  const vivo = useRef(true);

  const perguntar = useCallback(async () => {
    try {
      const { data } = await getEstadoImpressao();
      if (vivo.current) setEstado(data);
    } catch (e) {
      // De propósito, nada: ver a nota acima. O último estado conhecido fica.
    }
  }, []);

  useEffect(() => {
    vivo.current = true;
    if (!activo) return undefined;
    perguntar();
    const timer = setInterval(perguntar, INTERVALO_ESTADO_IMPRESSAO_MS);
    return () => {
      vivo.current = false;
      clearInterval(timer);
    };
  }, [activo, perguntar]);

  return { estado, recarregar: perguntar };
}
