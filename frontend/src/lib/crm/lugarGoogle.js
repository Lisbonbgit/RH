// Os lugares da Google no CRM: só a posição e a morada (plano do mapa Google,
// G9; adenda §6.3 e §2). É o único ficheiro do CRM que fala com a biblioteca
// `places` da Google (o seguranca.test.js recusa estes nomes em qualquer outro
// sítio) e pede sempre uma das duas listas fixas de campos:
//  - CAMPOS_POSICAO (só a `location`): o negócio tocado no mapa, e só quando a
//    pessoa toca na ação do painel ("Adicionar como loja" / "Pôr o pino neste
//    negócio");
//  - CAMPOS_MORADA_GOOGLE (a `location`, a `formattedAddress` e os
//    `addressComponents`): a morada escolhida na pesquisa da Google.
// Cada campo a mais muda o que a Google cobra e traria dados do negócio que o
// CRM nunca lê nem guarda (o nome e o telefone das lojas escrevem-se sempre à
// mão; para os ler, a pessoa toca no ícone do negócio e vê o balão da própria
// Google). Por isso as listas são constantes, o pedido dos campos só se
// escreve de uma forma neste ficheiro, e `pontoDoLugar`/`moradaDoLugar` leem
// só as suas chaves e devolvem objetos com chaves exatas.
//
// Uma coordenada da Google nunca se grava tal e qual: o seletor põe o pino com
// a origem passageira `google` e só deixa confirmar depois de a pessoa o
// arrastar até à porta da loja (`localizacao.js`); guarda-se o
// `google_place_id` ao lado do pino posto pela pessoa.
//
// A Google (`google`) chega por parâmetro, como no `mapa.js`: os componentes
// passam o `window.google` depois do `importar('places')` do carregador; os
// testes passam o Google falso de `testes/`.

import { pontoDe } from './mapa';

export const CAMPOS_POSICAO = Object.freeze(['location']);
export const CAMPOS_MORADA_GOOGLE = Object.freeze(['location', 'formattedAddress', 'addressComponents']);
// Os únicos campos de um lugar que o CRM alguma vez pede (o varrimento confere as duas listas de cima).
export const CAMPOS_PERMITIDOS = Object.freeze(['id', 'location', 'formattedAddress', 'addressComponents']);

// Os textos do painel do negócio e da pesquisa (cada um numa só linha).
export const ROTULO_NEGOCIO = 'Negócio selecionado';
export const TEXTO_NEGOCIO_SELECIONADO = 'Negócio selecionado no mapa.';
export const TEXTO_ADICIONAR_COMO_LOJA = 'Adicionar como loja';
export const TEXTO_USAR_ESTE_NEGOCIO = 'Pôr o pino neste negócio';
export const TEXTO_FECHAR_NEGOCIO = 'Fechar';
export const TEXTO_A_POSICIONAR = 'A posicionar o pino…';
export const TEXTO_LUGAR_INDISPONIVEL = 'Não foi possível obter a posição deste lugar — toque no mapa no sítio da loja.';
export const TEXTO_ESCREVA_O_NOME = 'Escreva o nome da loja como quer que apareça no mapa — para o ler, toque no ícone do negócio no mapa: abre o balão da Google (nada se copia).';
export const TEXTO_PESQUISAR_LUGAR = 'Pesquisar morada ou lugar (Google)';

// A localidade da loja, pela ordem: a cidade ou vila, a cidade do correio, a freguesia, o concelho.
const TIPOS_LOCALIDADE = Object.freeze([
  'locality',
  'postal_town',
  'administrative_area_level_3',
  'administrative_area_level_2',
]);
// Como no servidor (`crm/servicos/geoapify.py`): só o código postal completo.
const CODIGO_POSTAL = /^[0-9]{4}-[0-9]{3}$/;

const eObjeto = (valor) => valor !== null && typeof valor === 'object';

// O texto aparado, ou null se não for texto ou ficar vazio.
const textoOuNull = (valor) => {
  if (typeof valor !== 'string') return null;
  const texto = valor.trim();
  return texto === '' ? null : texto;
};

// Um identificador de lugar só serve se for um texto não vazio (a Google não documenta o formato).
const eIdDeLugar = (valor) => textoOuNull(valor) !== null;

// --- Funções puras ----------------------------------------------------------------------------------

// {id, lat, lng} de um lugar com a `location` pedida, ou null (sem id em texto, sem posição, números
// que não são finitos). A `location` chega ora como LatLng (lat()/lng() em função) ora como literal.
export function pontoDoLugar(lugar) {
  if (!eObjeto(lugar)) return null;
  const { id } = lugar;
  if (!eIdDeLugar(id)) return null;
  const ponto = pontoDe(lugar.location);
  return ponto === null ? null : { id, lat: ponto.lat, lng: ponto.lng };
}

// O primeiro texto (longText, aparado) de um componente da morada com este tipo, ou null.
function componente(componentes, tipo) {
  for (const parte of componentes) {
    if (!eObjeto(parte) || !Array.isArray(parte.types) || !parte.types.includes(tipo)) continue;
    const texto = textoOuNull(parte.longText);
    if (texto !== null) return texto;
  }
  return null;
}

// A morada de um lugar escolhido na pesquisa, na forma da sugestão da Geoapify (o formulário da loja
// já a conhece): {rotulo, morada, codigo_postal, localidade}.
//  - rotulo: a morada da Google por extenso, aparada (sem ela, null; o resto na mesma);
//  - morada: a rua com o número de polícia ("Rua Augusta 24"), só a rua sem número, null sem rua;
//  - codigo_postal: só no formato 0000-000;
//  - localidade: a primeira de TIPOS_LOCALIDADE que o lugar tiver.
export function moradaDoLugar(lugar) {
  const objeto = eObjeto(lugar);
  const rotulo = objeto ? textoOuNull(lugar.formattedAddress) : null;
  const componentes = objeto && Array.isArray(lugar.addressComponents) ? lugar.addressComponents : [];
  const rua = componente(componentes, 'route');
  const numero = componente(componentes, 'street_number');
  const codigo = componente(componentes, 'postal_code');
  let localidade = null;
  for (const tipo of TIPOS_LOCALIDADE) {
    localidade = componente(componentes, tipo);
    if (localidade !== null) break;
  }
  return {
    rotulo,
    morada: rua === null ? null : [rua, numero].filter((parte) => parte !== null).join(' '),
    codigo_postal: codigo !== null && CODIGO_POSTAL.test(codigo) ? codigo : null,
    localidade,
  };
}

// --- Os pedidos à Google ----------------------------------------------------------------------------

// A posição de um negócio tocado no mapa (só a `location`) → {id, lat, lng}. Rejeita se o identificador
// não for um texto (antes de pedir o que quer que seja), se a Google falhar (p. ex. NOT_FOUND) ou se o
// lugar vier sem posição.
export async function posicaoDoLugar(google, placeId) {
  if (!eIdDeLugar(placeId)) throw new Error('lugar sem identificador');
  const lugar = new google.maps.places.Place({ id: placeId });
  const resposta = await lugar.fetchFields({ fields: CAMPOS_POSICAO });
  const ponto = pontoDoLugar(resposta?.place ?? lugar);
  if (ponto === null) throw new Error('lugar sem posição');
  return ponto;
}

// A sugestão escolhida na pesquisa da Google → {id, lat, lng, morada}. Rejeita se a Google falhar ou se
// o lugar vier sem posição. (O `google` não faz falta aqui: a previsão já traz o lugar; fica pela forma.)
export async function lugarDaPesquisa(google, previsao) {
  const lugar = previsao.toPlace();
  const resposta = await lugar.fetchFields({ fields: CAMPOS_MORADA_GOOGLE });
  const escolhido = resposta?.place ?? lugar;
  const ponto = pontoDoLugar(escolhido);
  if (ponto === null) throw new Error('lugar sem posição');
  return { ...ponto, morada: moradaDoLugar(escolhido) };
}

// --- A pesquisa da Google ---------------------------------------------------------------------------

// O elemento de pesquisa da própria Google (GA), só com lugares de Portugal. A pessoa escreve nele e a
// Google mostra as sugestões e gere a sessão de faturação; o CRM só ouve três eventos:
//  - ao focar, as sugestões passam a preferir a zona à vista no mapa (`obterLimites()`, ou nenhuma);
//  - 'gmp-select' (escolheu uma sugestão) → `lugarDaPesquisa` → `aoEscolher({id, lat, lng, morada})`;
//    uma escolha feita enquanto outra carrega substitui-a (só a última conta, mesmo que a outra chegue
//    depois ou falhe depois); se o pedido falhar → `aoFalhar()` e nada mais. Com `aoComecar`, chamado no
//    instante da escolha (antes do pedido), a função que ele devolver diz, quando a resposta chega, se a
//    escolha ainda vale (o seletor: a pessoa pode ter posto o pino noutro sítio entretanto); se não valer,
//    nem `aoEscolher` nem `aoFalhar` (revisão do mapa Google, G-ENG-2);
//  - 'gmp-error' (a Google não conseguiu sugerir) → `aoFalhar()`.
// O elemento junta-se ao DOM pelo componente (`PesquisaLugar`, por ref). `destruir()` desliga os
// eventos, ignora o que ainda estiver a carregar e tira o elemento de onde estiver. Sem a biblioteca
// `places` não há pesquisa: `elemento` é null.
export function criarPesquisaLugar({ google, aoEscolher, aoFalhar, obterLimites, aoComecar } = {}) {
  const Pesquisa = google?.maps?.places?.PlaceAutocompleteElement;
  if (typeof Pesquisa !== 'function') return { elemento: null, destruir() {} };

  const elemento = new Pesquisa({ includedRegionCodes: ['pt'] });
  let ativa = true;
  let escolha = 0;

  function aoFocar() {
    if (!ativa) return;
    elemento.locationBias = obterLimites?.() ?? undefined;
  }

  function aoSelecionar(evento) {
    if (!ativa) return;
    escolha += 1;
    const minha = escolha;
    // Quem usa a pesquisa (o seletor) sabe que começou outra escolha e diz depois se esta ainda vale.
    const paraQuemUsa = aoComecar?.();
    const valeAinda = () => ativa && minha === escolha
      && (typeof paraQuemUsa !== 'function' || paraQuemUsa() === true);
    lugarDaPesquisa(google, evento?.placePrediction).then(
      (lugar) => {
        if (valeAinda()) aoEscolher?.(lugar);
      },
      () => {
        if (valeAinda()) aoFalhar?.();
      },
    );
  }

  function aoErro() {
    if (ativa) aoFalhar?.();
  }

  elemento.addEventListener('focus', aoFocar);
  elemento.addEventListener('gmp-select', aoSelecionar);
  elemento.addEventListener('gmp-error', aoErro);

  function destruir() {
    if (!ativa) return;
    ativa = false;
    elemento.removeEventListener('focus', aoFocar);
    elemento.removeEventListener('gmp-select', aoSelecionar);
    elemento.removeEventListener('gmp-error', aoErro);
    elemento.remove?.();
  }

  return { elemento, destruir };
}

// --- O painel do negócio selecionado ----------------------------------------------------------------

// O controlador do painel ao lado do mapa (`components/crm/NegocioSelecionado.js`), sem DOM. A `vista`
// é nova e congelada a cada mudança e tem sempre só quatro chaves: {placeId, reserva, estado, mensagem}
// — nenhum dado da Google (nem nome, nem morada, nem foto). `reserva` é o ponto tocado ({lat, lng}),
// para pôr o pino se a posição do lugar não chegar.
//  - abrir(placeId, {reserva}) → 'aberto' (outro negócio substitui o anterior; um identificador que
//    não seja texto não vazio é ignorado);
//  - aPosicionar() → 'a_posicionar', com TEXTO_A_POSICIONAR (a pessoa tocou na ação);
//  - falhou(mensagem?) → 'erro', com a mensagem ou TEXTO_LUGAR_INDISPONIVEL;
//  - fechar() → 'fechado', sem placeId nem reserva;
//  - destruir() → nada mais muda nem avisa.
// Fechado, `aPosicionar()` e `falhou()` não fazem nada.
export function criarNegocioSelecionado({ aoMudarVista } = {}) {
  let ativo = true;
  let vista = Object.freeze({ placeId: null, reserva: null, estado: 'fechado', mensagem: null });

  function mudar(placeId, reserva, estado, mensagem) {
    vista = Object.freeze({ placeId, reserva, estado, mensagem });
    aoMudarVista?.(vista);
  }

  function reservaDe(reserva) {
    const ponto = pontoDe(reserva);
    return ponto === null ? null : Object.freeze({ lat: ponto.lat, lng: ponto.lng });
  }

  return {
    get vista() {
      return vista;
    },
    abrir(placeId, opcoes) {
      if (!ativo || !eIdDeLugar(placeId)) return;
      mudar(placeId, reservaDe(opcoes?.reserva), 'aberto', null);
    },
    aPosicionar() {
      if (!ativo || vista.estado === 'fechado') return;
      mudar(vista.placeId, vista.reserva, 'a_posicionar', TEXTO_A_POSICIONAR);
    },
    falhou(mensagem) {
      if (!ativo || vista.estado === 'fechado') return;
      mudar(vista.placeId, vista.reserva, 'erro', textoOuNull(mensagem) ?? TEXTO_LUGAR_INDISPONIVEL);
    },
    fechar() {
      if (!ativo || vista.estado === 'fechado') return;
      mudar(null, null, 'fechado', null);
    },
    destruir() {
      ativo = false;
    },
  };
}
