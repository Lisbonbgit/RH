// Regras da localização escolhida no seletor (pino manual, GPS ou um lugar da
// Google). Funções puras. Porta de public/assets/js/localizacao.js do CRM
// autónomo; as regras do servidor estão no dossiê §5.2 e §5.4.
//
// Mapa Google (plano G9; adenda §2.1, decisão 2): `google` é uma origem só do
// seletor (o negócio tocado no mapa ou a morada escolhida na pesquisa da
// Google). Uma coordenada da Google nunca se grava tal e qual: o pino só se
// confirma depois de a pessoa o arrastar até à porta da loja, e a origem
// enviada é sempre `pin_manual` (o servidor recusa `google` com 422). O
// identificador do lugar vai ao lado, no `google_place_id`.
import { avaliarPrecisao } from './gps';

// Se o pino foi arrastado, a localização passa a ser do utilizador. A origem `google` nunca sai do seletor.
export function origemFinal(origemInicial, arrastado) {
  return arrastado || origemInicial === 'google' ? 'pin_manual' : origemInicial;
}

// "Confirmar" só fica ativo depois de arrastar o pino com um ponto da Google e com um GPS impreciso (> 50 m).
export function podeConfirmar({ origem, precisao_m, arrastado }) {
  if (arrastado) return true;
  if (origem === 'google') return false;
  if (origem !== 'gps') return true;
  return avaliarPrecisao(precisao_m) === 'ok';
}

// O identificador do lugar da Google, só se for um texto não vazio.
function idDoLugar(valor) {
  return typeof valor === 'string' && valor.trim() !== '' ? valor : null;
}

// Bloco a enviar à API (o mesmo do `CAMPOS_LOCALIZACAO` do diferencas.js). `precisao_m` só existe para
// origem gps (arredondada); nas outras é null. `google_place_id`: o do lugar da Google, ou null.
export function localizacaoFinal({ lat, lng, origem, precisao_m, google_place_id }, arrastado) {
  const origem_coords = origemFinal(origem, arrastado);
  return {
    lat,
    lng,
    origem_coords,
    precisao_m: origem_coords === 'gps' && Number.isFinite(precisao_m) ? Math.round(precisao_m) : null,
    google_place_id: idDoLugar(google_place_id),
  };
}
