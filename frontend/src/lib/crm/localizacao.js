// Regras da localização escolhida no seletor (pino manual, pesquisa de morada
// ou GPS). Funções puras. Porta de public/assets/js/localizacao.js do CRM
// autónomo, tal e qual. As regras do servidor estão no dossiê §5.2 e §5.4.
import { avaliarPrecisao } from './gps';

// Se o pino foi arrastado, a localização passa a ser do utilizador.
export function origemFinal(origemInicial, arrastado) {
  return arrastado ? 'pin_manual' : origemInicial;
}

// GPS impreciso (> 50 m): "Confirmar" só fica ativo depois de arrastar o pino.
export function podeConfirmar({ origem, precisao_m, arrastado }) {
  if (origem !== 'gps' || arrastado) return true;
  return avaliarPrecisao(precisao_m) === 'ok';
}

// Bloco a enviar à API. `precisao_m` só existe para origem gps (arredondada); nas outras é null.
export function localizacaoFinal({ lat, lng, origem, precisao_m }, arrastado) {
  const origem_coords = origemFinal(origem, arrastado);
  return {
    lat,
    lng,
    origem_coords,
    precisao_m: origem_coords === 'gps' && Number.isFinite(precisao_m) ? Math.round(precisao_m) : null,
  };
}
