// Pesquisa de morada (autocompletar) com espera entre teclas e proteção contra
// respostas fora de ordem. Porta de public/assets/js/morada.js do CRM
// autónomo. Pura: a `api` é injetada — `api(texto, extra)` devolve uma Promise
// com a lista de sugestões (GET /api/crm/morada/pesquisa) e rejeita com
// {codigo, mensagem} (o ErroCrm do api.js: 'morada_indisponivel', 'sem_rede').
//
// As duas mensagens têm de ser as do 503 de backend/crm/morada.py
// (PESQUISA_INDISPONIVEL e INVERSA_INDISPONIVEL), verificado pelo
// backend/tests/crm/test_consistencia_frontend.py: manter cada uma numa só
// linha `export const <nome> = '<texto>';` (ou entre aspas duplas).

export const MENSAGEM_MORADA_INDISPONIVEL = "Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'";

// A geocodificação inversa do "Estou nesta loja" falhou (o texto do 503 do servidor, também sem rede).
export const MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL = 'Morada sugerida indisponível — escreva a morada à mão.';

// Estados enviados a `aoMudarEstado`:
//   {estado:'vazio', sugestoes:[]}                      texto com menos de `minimo` caracteres
//   {estado:'a_pesquisar', texto}                       pedido enviado
//   {estado:'resultados', texto, sugestoes}             resposta do pedido mais recente
//   {estado:'erro', codigo, mensagem}                   falha ('sem_rede' ou 'morada_indisponivel')
export function criarPesquisaMorada({ api, aoMudarEstado, atrasoMs = 300, minimo = 3 }) {
  let temporizador = null;
  // Cada tecla ou cancelamento incrementa a sequência; só a resposta do pedido mais recente conta.
  let sequencia = 0;

  function cancelar() {
    if (temporizador !== null) {
      clearTimeout(temporizador);
      temporizador = null;
    }
    sequencia += 1;
  }

  function pesquisar(texto, extra) {
    temporizador = null;
    const minha = sequencia;
    aoMudarEstado({ estado: 'a_pesquisar', texto });

    let promessa;
    try {
      promessa = Promise.resolve(api(texto, extra));
    } catch (erro) {
      promessa = Promise.reject(erro);
    }

    promessa.then(
      (sugestoes) => {
        if (minha !== sequencia) return;
        aoMudarEstado({ estado: 'resultados', texto, sugestoes: Array.isArray(sugestoes) ? sugestoes : [] });
      },
      (erro) => {
        if (minha !== sequencia) return;
        const codigo = erro?.codigo === 'sem_rede' ? 'sem_rede' : 'morada_indisponivel';
        aoMudarEstado({ estado: 'erro', codigo, mensagem: MENSAGEM_MORADA_INDISPONIVEL });
      },
    );
  }

  function escrever(texto, extra) {
    cancelar();
    const limpo = String(texto ?? '').trim();
    if (limpo.length < minimo) {
      aoMudarEstado({ estado: 'vazio', sugestoes: [] });
      return;
    }
    temporizador = setTimeout(() => pesquisar(limpo, extra), atrasoMs);
  }

  return { escrever, cancelar };
}

// --- A sugestão escolhida (plano E6 do autónomo) -------------------------------------------------

// Os campos da loja que a sugestão escolhida preenche.
export const CAMPOS_MORADA = Object.freeze(['morada', 'codigo_postal', 'localidade']);

const textoPreenchido = (valor) => (typeof valor === 'string' ? valor.trim() : '');

// Os campos a mudar no formulário com a sugestão escolhida ({morada?, codigo_postal?, localidade?}).
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

// O ponto que ordena as sugestões (bias): até 6 casas decimais (cerca de 10 cm), para o número nunca ir com
// expoente (o servidor só aceita números escritos por extenso). Sem um ponto válido, null (pesquisa sem bias).
export function pontoDeBias(ponto) {
  const lat = ponto?.lat;
  const lng = ponto?.lng;
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat: Number(lat.toFixed(6)) || 0, lng: Number(lng.toFixed(6)) || 0 };
}
