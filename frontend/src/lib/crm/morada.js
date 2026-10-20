// A morada da loja: os campos que a morada escolhida ou a sugerida preenchem e
// o ponto da geocodificação inversa. Porta de public/assets/js/morada.js do
// CRM autónomo. A pesquisa de moradas da Geoapify (o autocompletar com espera
// entre teclas, `criarPesquisaMorada`, e a mensagem do 503 dela) saiu na G11
// do plano do mapa Google: a pesquisa é o elemento da própria Google
// (`lugarGoogle.js`, no seletor), e a morada que ele dá chega na mesma forma
// ({rotulo, morada, codigo_postal, localidade, lat, lng}). A Geoapify fica só
// para a morada sugerida do GPS (GET /api/crm/morada/inversa).
//
// A mensagem da morada sugerida indisponível tem de ser a do 503 de
// backend/crm/morada.py (INVERSA_INDISPONIVEL), verificado pelo
// backend/tests/crm/test_consistencia_frontend.py: manter numa só linha
// `export const <nome> = '<texto>';` (ou entre aspas duplas).

// A geocodificação inversa do "Estou nesta loja" falhou (o texto do 503 do servidor, também sem rede).
export const MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL = 'Morada sugerida indisponível — escreva a morada à mão.';

// --- A sugestão escolhida (plano E6 do autónomo) -------------------------------------------------

// Os campos da loja que a sugestão escolhida preenche.
export const CAMPOS_MORADA = Object.freeze(['morada', 'codigo_postal', 'localidade']);

const textoPreenchido = (valor) => (typeof valor === 'string' ? valor.trim() : '');

// Os campos a mudar no formulário com a morada escolhida na pesquisa ({morada?, codigo_postal?, localidade?}).
//  - O que a sugestão tem substitui o que lá estava (a pessoa escolheu esta morada).
//  - O que a sugestão não tem só se esvazia se o campo ainda tiver o que a sugestão anterior lá pôs
//    (`anteriores`): assim não fica o código postal de outra rua, e o que a pessoa escreveu fica.
export function camposDaMorada(sugestao, atuais = {}, anteriores = {}) {
  const campos = {};
  for (const campo of CAMPOS_MORADA) {
    const valor = textoPreenchido(sugestao?.[campo]);
    if (valor !== '') campos[campo] = valor;
    else if (typeof anteriores?.[campo] === 'string' && atuais?.[campo] === anteriores[campo]) campos[campo] = '';
  }
  return campos;
}

// Os campos a mudar no formulário com a morada sugerida pelo GPS (geocodificação inversa, plano E7 do
// autónomo). A sugestão é só um palpite a partir do ponto, por isso nunca toca no que a pessoa escreveu:
//  - preenche os campos vazios e os que ainda têm o que a app lá pôs antes (`anteriores`: outra morada
//    sugerida ou escolhida na pesquisa) sem a pessoa os ter mudado;
//  - nesses, o que a sugestão não tem esvazia-se (não fica o código postal de outro sítio).
export function camposSugeridos(sugestao, atuais = {}, anteriores = {}) {
  const campos = {};
  for (const campo of CAMPOS_MORADA) {
    const atual = typeof atuais?.[campo] === 'string' ? atuais[campo] : '';
    const daApp = typeof anteriores?.[campo] === 'string' && atual === anteriores[campo];
    if (atual.trim() !== '' && !daApp) continue;
    const valor = textoPreenchido(sugestao?.[campo]);
    if (valor !== '') campos[campo] = valor;
    else if (daApp && atual !== '') campos[campo] = '';
  }
  return campos;
}

// O ponto da morada inversa (o do GPS): até 6 casas decimais (cerca de 10 cm), para o número nunca ir com
// expoente (o servidor só aceita números escritos por extenso). Sem um ponto válido, null.
export function pontoDeBias(ponto) {
  const lat = ponto?.lat;
  const lng = ponto?.lng;
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat: Number(lat.toFixed(6)) || 0, lng: Number(lng.toFixed(6)) || 0 };
}
